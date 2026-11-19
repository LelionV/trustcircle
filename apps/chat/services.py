"""
Who may talk to whom, sending and reading messages, and reports.

Loan chats are between two people connected by a loan:
  * the borrower and anyone who invested in it or made an offer on it,
  * the borrower and its (requested) guarantor,
  * an investor who is looking at a loan on the marketplace and its borrower.
Customers can also open a support chat with staff.
"""
import re

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone

from apps.accounts.permissions import has_permission
from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation
from apps.notifications.services import notify, notify_admins

from .models import (
    Conversation,
    ConversationKind,
    Message,
    MessageKind,
    Participant,
    ReportStatus,
    UserReport,
)

PHONE_OR_PAYMENT = re.compile(r"(\+?254|\b0)[17]\d{8}\b|\b(till|paybill|send money|mpesa me)\b", re.I)
SAFETY_NOTICE = ("Safety: never send or lend money outside P2P Lend. Payments made outside the platform aren't "
                 "protected, recorded or recoverable.")


def display_name(user):
    if user is None:
        return "P2P Lend"
    if user.role == "ADMIN":
        return f"{user.first_name or 'Staff'} (P2P Lend support)"
    initial = (user.last_name[:1] + ".") if user.last_name else ""
    return f"{user.first_name} {initial}".strip() or "Member"


def _pair(a, b):
    return ":".join(sorted([str(a.pk), str(b.pk)]))


def _connected(loan, user):
    """How `user` is connected to `loan` (None if not)."""
    from apps.loans.models import MARKETPLACE_STATUSES

    if loan.borrower_id == user.pk:
        return "borrower"
    if loan.investments.filter(investor=user).exclude(status="REFUNDED").exists():
        return "investor"
    if loan.offers.filter(investor=user).exists():
        return "offer"
    if loan.guarantees.filter(guarantor=user).exists() or loan.proposed_guarantor_id == user.pk:
        return "guarantor"
    if loan.status in MARKETPLACE_STATUSES and has_permission(user, "marketplace.view"):
        return "prospect"
    return None


def can_chat(user, other, loan):
    if user.pk == other.pk:
        return False
    a, b = _connected(loan, user), _connected(loan, other)
    # Every loan chat has the borrower on one side.
    return (a == "borrower" and b in ("investor", "offer", "guarantor", "prospect")) or \
           (b == "borrower" and a in ("investor", "offer", "guarantor", "prospect"))


def _get_or_create_loan_chat(loan, a, b):
    key = _pair(a, b)
    conv = Conversation.objects.filter(kind=ConversationKind.LOAN, loan=loan, pair_key=key).first()
    if conv is None:
        try:
            with transaction.atomic():
                conv = Conversation.objects.create(kind=ConversationKind.LOAN, loan=loan, pair_key=key)
                Participant.objects.bulk_create([Participant(conversation=conv, user=a),
                                                 Participant(conversation=conv, user=b)])
        except IntegrityError:
            conv = Conversation.objects.get(kind=ConversationKind.LOAN, loan=loan, pair_key=key)
    return conv


def start_loan_chat(user, loan, other=None):
    if other is None:
        if loan.borrower_id == user.pk:
            raise BusinessRuleViolation("Choose who to message.", code="recipient_required")
        other = loan.borrower
    if not can_chat(user, other, loan):
        raise BusinessRuleViolation("You can only message people connected to you through this loan.",
                                    code="not_connected")
    return _get_or_create_loan_chat(loan, user, other)


def open_support(user):
    conv = Conversation.objects.filter(kind=ConversationKind.SUPPORT, participants__user=user,
                                       pair_key=str(user.pk)).first()
    if conv is None:
        conv = Conversation.objects.create(kind=ConversationKind.SUPPORT, pair_key=str(user.pk))
        Participant.objects.create(conversation=conv, user=user)
    return conv


def can_view(user, conv):
    if conv.participants.filter(user=user).exists():
        return True
    if conv.kind == ConversationKind.SUPPORT and has_permission(user, "admin.support.chat"):
        return True
    return has_permission(user, "admin.moderation.view") and conv.reports.exists()


def _post(conv, sender, body, kind=MessageKind.TEXT, offer=None):
    msg = Message.objects.create(conversation=conv, sender=sender, body=body[:2000], kind=kind, offer=offer)
    Conversation.objects.filter(pk=conv.pk).update(last_message_at=msg.created_at)
    return msg


@transaction.atomic
def send(user, conv_id, body):
    conv = Conversation.objects.select_for_update().get(pk=conv_id)
    body = (body or "").strip()
    if not body:
        raise BusinessRuleViolation("Write a message first.", code="empty_message")
    if len(body) > 2000:
        raise BusinessRuleViolation("Messages can be up to 2,000 characters.", code="too_long")
    is_member = conv.participants.filter(user=user).exists()
    if not is_member:
        if conv.kind == ConversationKind.SUPPORT and has_permission(user, "admin.support.chat"):
            Participant.objects.get_or_create(conversation=conv, user=user)
        else:
            raise BusinessRuleViolation("You're not in this conversation.", code="not_participant")
    if conv.blocked_by_id:
        raise BusinessRuleViolation("This conversation has been blocked.", code="blocked")
    msg = _post(conv, user, body)
    Participant.objects.filter(conversation=conv, user=user).update(last_read_at=msg.created_at)
    if PHONE_OR_PAYMENT.search(body) and not conv.messages.filter(kind=MessageKind.SYSTEM,
                                                                  body=SAFETY_NOTICE).exists():
        _post(conv, None, SAFETY_NOTICE, MessageKind.SYSTEM)
    for p in conv.participants.exclude(user=user).select_related("user"):
        notify(p.user, "chat_message", f"Message from {display_name(user)}", body[:140], f"#/chat/{conv.pk}",
               dedupe_key=f"chat-{conv.pk}-{timezone.now():%Y%m%d%H}")  # at most one alert per hour per chat
    if conv.kind == ConversationKind.SUPPORT and user.role != "ADMIN" and conv.participants.count() == 1:
        notify_admins("admin.support.chat", "support_message", "New support message",
                      f"{user.full_name}: {body[:100]}", f"#/chat/{conv.pk}")
    return msg


def post_system(*, loan, members, text, kind=MessageKind.SYSTEM, offer=None):
    """Called by the offers service: record an offer event in the borrower–investor chat."""
    a, b = members
    conv = _get_or_create_loan_chat(loan, a, b)
    return _post(conv, None, text, kind, offer)


def conversations_for(user):
    last_body = Message.objects.filter(conversation=OuterRef("pk")).order_by("-created_at", "-id").values("body")[:1]
    qs = Conversation.objects.filter(participants__user=user).select_related("loan").annotate(
        last_body=Subquery(last_body))
    result = []
    for conv in qs:
        me = conv.participants.get(user=user)
        others = [p.user for p in conv.participants.exclude(user=user).select_related("user")]
        unread = conv.messages.exclude(sender=user)
        if me.last_read_at:
            unread = unread.filter(created_at__gt=me.last_read_at)
        result.append({
            "id": conv.pk, "kind": conv.kind,
            "title": ("Support" if conv.kind == ConversationKind.SUPPORT
                      else ", ".join(display_name(o) for o in others) or "Conversation"),
            "loan": {"id": conv.loan_id, "reference": conv.loan.reference} if conv.loan_id else None,
            "last_message": (conv.last_body or "")[:120], "last_message_at": conv.last_message_at,
            "unread": unread.count(), "blocked": bool(conv.blocked_by_id),
        })
    return result


def unread_total(user):
    return sum(c["unread"] for c in conversations_for(user))


def messages(user, conv, after=None):
    qs = conv.messages.select_related("sender", "offer")
    if after:
        qs = qs.filter(id__gt=after)
    rows = list(qs[:500])
    if rows:
        Participant.objects.filter(conversation=conv, user=user).update(last_read_at=rows[-1].created_at)
    return rows


@transaction.atomic
def set_blocked(user, conv_id, blocked):
    conv = Conversation.objects.select_for_update().get(pk=conv_id, participants__user=user)
    if conv.kind == ConversationKind.SUPPORT:
        raise BusinessRuleViolation("Support chats can't be blocked.", code="not_blockable")
    if blocked:
        conv.blocked_by = user
    elif conv.blocked_by_id == user.pk:
        conv.blocked_by = None
    else:
        raise BusinessRuleViolation("Only the person who blocked this chat can unblock it.", code="not_blocker")
    conv.save(update_fields=["blocked_by"])
    _post(conv, None, "This chat was blocked." if blocked else "This chat was unblocked.", MessageKind.SYSTEM)
    return conv


# --- Reports --------------------------------------------------------------------------------

@transaction.atomic
def report(reporter, *, reason, details, user=None, message=None, loan=None, request=None):
    conv = None
    if message is not None:
        conv = message.conversation
        if not conv.participants.filter(user=reporter).exists():
            raise BusinessRuleViolation("You can only report messages in your own chats.", code="not_participant")
        if message.sender is None:
            raise BusinessRuleViolation("Automatic notices can't be reported.", code="not_reportable")
        user = message.sender
    elif loan is not None and user is None:
        user = loan.borrower
    if user is None:
        raise BusinessRuleViolation("Choose who you're reporting.", code="reported_required")
    if user.pk == reporter.pk:
        raise BusinessRuleViolation("You can't report yourself.", code="self_report")
    if message is None and loan is None and not Conversation.objects.filter(
            participants__user=reporter).filter(participants__user=user).exists():
        raise BusinessRuleViolation("You can only report people you've dealt with on the platform.",
                                    code="not_connected")
    if UserReport.objects.filter(reporter=reporter, reported=user, status=ReportStatus.OPEN).exists():
        raise BusinessRuleViolation("You've already reported this person; we're looking into it.",
                                    code="already_reported")
    r = UserReport.objects.create(reporter=reporter, reported=user, reason=reason, details=details.strip(),
                                  message=message, conversation=conv)
    audit.record(action="user.reported", entity_type="UserReport", entity_id=r.pk, actor=reporter,
                 after={"reported": user.email, "reason": reason}, request=request)
    notify_admins("admin.moderation.manage", "user_reported", "A user was reported",
                  f"{display_name(user)} reported for {r.get_reason_display().lower()}.", "#/admin/moderation")
    return r


def report_counts(user):
    return UserReport.objects.filter(reported=user).aggregate(
        total=Count("pk"), open=Count("pk", filter=Q(status=ReportStatus.OPEN)),
        actioned=Count("pk", filter=Q(status__in=[ReportStatus.WARNED, ReportStatus.ACTIONED])))


@transaction.atomic
def resolve_report(report_id, actor, *, action, note, request=None):
    """action: DISMISS, WARN, HIDE_MESSAGE or FREEZE (freeze needs admin.accounts.freeze)."""
    from apps.administration.services import set_account_frozen

    r = UserReport.objects.select_for_update().select_related("reported", "reporter", "message").get(pk=report_id)
    if r.status != ReportStatus.OPEN:
        raise BusinessRuleViolation("This report has already been dealt with.", code="already_resolved")
    if r.reported_id == actor.pk:
        raise BusinessRuleViolation("You can't review a report about yourself.", code="self_review")
    if action == "DISMISS":
        r.status = ReportStatus.DISMISSED
    elif action == "WARN":
        r.status = ReportStatus.WARNED
        notify(r.reported, "moderation_warning", "A warning about your conduct",
               f"After a report, our team asks you to follow the platform rules: {note}", "#/notifications")
    elif action == "HIDE_MESSAGE":
        if r.message is None:
            raise BusinessRuleViolation("This report isn't about a message.", code="no_message")
        r.message.hidden_by_moderator = True
        r.message.save(update_fields=["hidden_by_moderator"])
        r.status = ReportStatus.ACTIONED
    elif action == "FREEZE":
        if not has_permission(actor, "admin.accounts.freeze"):
            raise BusinessRuleViolation("You can't freeze accounts.", code="permission_denied")
        set_account_frozen(actor=actor, target_id=r.reported_id, frozen=True, reason=f"Report: {note}",
                           request=request)
        r.status = ReportStatus.ACTIONED
    else:
        raise BusinessRuleViolation("Unknown action.", code="invalid_action")
    r.reviewed_by, r.reviewed_at, r.resolution = actor, timezone.now(), note
    r.save()
    audit.record(action=f"report.{action.lower()}", entity_type="UserReport", entity_id=r.pk, actor=actor,
                 reason=note, request=request)
    notify(r.reporter, "report_reviewed", "We've reviewed your report",
           "Thanks for reporting. Our team has reviewed it and taken the action it judged appropriate.",
           "#/notifications")
    return r

