from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.common.api import ok, paginated, validated
from apps.common.exceptions import BusinessRuleViolation
from apps.common.permissions import HasPlatformPermission
from apps.loans.models import Loan

from . import services
from .models import Conversation, Message, ReportReason, ReportStatus, UserReport


def message_row(m, me):
    hidden = m.hidden_by_moderator
    return {
        "id": m.pk, "kind": m.kind, "body": "This message was removed by a moderator." if hidden else m.body,
        "hidden": hidden, "mine": m.sender_id == me.pk, "sender": services.display_name(m.sender) if m.sender_id
        else "P2P Lend", "sender_id": m.sender_id, "created_at": m.created_at,
        "offer": None if m.offer_id is None else {
            "id": m.offer.pk, "amount": str(m.offer.amount), "rate": str(m.offer.rate), "status": m.offer.status,
            "status_label": m.offer.get_status_display(), "loan_id": m.offer.loan_id,
            "investor_id": m.offer.investor_id},
    }


def conversation_detail(conv, me):
    others = [p.user for p in conv.participants.exclude(user=me).select_related("user")]
    loan = conv.loan
    return {
        "id": conv.pk, "kind": conv.kind,
        "title": "Support" if conv.kind == "SUPPORT" else ", ".join(services.display_name(o) for o in others),
        "others": [{"id": o.pk, "name": services.display_name(o)} for o in others],
        "loan": None if loan is None else {
            "id": loan.pk, "reference": loan.reference, "status": loan.status,
            "status_label": loan.get_status_display(), "amount": str(loan.amount),
            "funding_mode": loan.funding_mode, "i_am_borrower": loan.borrower_id == me.pk},
        "blocked": bool(conv.blocked_by_id), "blocked_by_me": conv.blocked_by_id == me.pk,
    }


class ConversationsView(APIView):
    """GET your chats. POST {loan_id, user_id?} to open the chat about a loan (or {support: true})."""

    permission_classes = [HasPlatformPermission]
    required_permission = "chat.use"

    class Input(serializers.Serializer):
        loan_id = serializers.UUIDField(required=False)
        user_id = serializers.UUIDField(required=False)
        support = serializers.BooleanField(default=False)

    @extend_schema(tags=["chat"])
    def get(self, request):
        return ok(services.conversations_for(request.user))

    @extend_schema(tags=["chat"], request=Input)
    def post(self, request):
        d = validated(self.Input, request.data)
        if d["support"]:
            conv = services.open_support(request.user)
        else:
            if not d.get("loan_id"):
                raise BusinessRuleViolation("Choose a loan.", code="loan_required")
            loan = get_object_or_404(Loan, pk=d["loan_id"])
            other = get_object_or_404(User, pk=d["user_id"]) if d.get("user_id") else None
            conv = services.start_loan_chat(request.user, loan, other)
        return ok(conversation_detail(conv, request.user), status=201)


class ConversationView(APIView):
    """GET messages (?after=<id> for new ones only). POST {body} to send."""

    permission_classes = [HasPlatformPermission]
    required_permission = "notifications.view"  # chat.use or staff access is checked per conversation below
    throttle_scope = "chat"

    class Input(serializers.Serializer):
        body = serializers.CharField(max_length=2000)

    def _conv(self, request, pk):
        conv = get_object_or_404(Conversation.objects.select_related("loan"), pk=pk)
        if not services.can_view(request.user, conv):
            raise BusinessRuleViolation("You're not in this conversation.", code="not_participant")
        return conv

    @extend_schema(tags=["chat"])
    def get(self, request, pk):
        conv = self._conv(request, pk)
        after = request.query_params.get("after")
        rows = services.messages(request.user, conv, int(after) if after and after.isdigit() else None)
        return ok({**conversation_detail(conv, request.user),
                   "messages": [message_row(m, request.user) for m in rows]})

    @extend_schema(tags=["chat"], request=Input)
    def post(self, request, pk):
        self._conv(request, pk)
        d = validated(self.Input, request.data)
        msg = services.send(request.user, pk, d["body"])
        return ok(message_row(msg, request.user), status=201)


class BlockView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "chat.use"

    class Input(serializers.Serializer):
        blocked = serializers.BooleanField()

    @extend_schema(tags=["chat"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        conv = services.set_blocked(request.user, pk, d["blocked"])
        return ok(conversation_detail(conv, request.user))


class ReportView(APIView):
    """Report a person: {message_id} or {user_id} (someone you've chatted with) or {loan_id} (its borrower)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "users.report"

    class Input(serializers.Serializer):
        reason = serializers.ChoiceField(choices=ReportReason.choices)
        details = serializers.CharField(min_length=10, max_length=2000)
        message_id = serializers.IntegerField(required=False)
        user_id = serializers.UUIDField(required=False)
        loan_id = serializers.UUIDField(required=False)

    @extend_schema(tags=["chat"])
    def get(self, request):
        return ok({"reasons": [{"value": v, "label": l} for v, l in ReportReason.choices],
                   "mine": [{"id": r.pk, "reported": services.display_name(r.reported), "reason": r.get_reason_display(),
                             "status": r.status, "status_label": r.get_status_display(), "created_at": r.created_at}
                            for r in UserReport.objects.filter(reporter=request.user).select_related("reported")[:50]]})

    @extend_schema(tags=["chat"], request=Input)
    def post(self, request):
        d = validated(self.Input, request.data)
        message = get_object_or_404(Message, pk=d["message_id"]) if d.get("message_id") else None
        user = get_object_or_404(User, pk=d["user_id"]) if d.get("user_id") else None
        loan = get_object_or_404(Loan, pk=d["loan_id"]) if d.get("loan_id") else None
        r = services.report(request.user, reason=d["reason"], details=d["details"], user=user, message=message,
                            loan=loan, request=request)
        return ok({"id": r.pk, "status": r.status}, status=201)


# --- Staff: moderation and support -------------------------------------------------------------

def report_row(r, detail=False):
    row = {
        "id": r.pk, "reason": r.reason, "reason_label": r.get_reason_display(), "details": r.details,
        "status": r.status, "status_label": r.get_status_display(), "created_at": r.created_at,
        "reporter": {"id": r.reporter_id, "name": r.reporter.full_name, "email": r.reporter.email},
        "reported": {"id": r.reported_id, "name": r.reported.full_name, "email": r.reported.email,
                     "is_frozen": r.reported.is_frozen, **services.report_counts(r.reported)},
        "message": None if r.message_id is None else {"id": r.message.pk, "body": r.message.body,
                                                      "at": r.message.created_at,
                                                      "hidden": r.message.hidden_by_moderator},
        "conversation_id": r.conversation_id, "resolution": r.resolution,
        "reviewed_by": r.reviewed_by.email if r.reviewed_by_id else None, "reviewed_at": r.reviewed_at,
    }
    if detail and r.conversation_id:
        msgs = r.conversation.messages.select_related("sender").order_by("-created_at")[:30]
        row["context"] = [{"id": m.pk, "sender": m.sender.full_name if m.sender_id else "P2P Lend",
                           "body": m.body, "at": m.created_at, "reported": m.pk == r.message_id}
                          for m in reversed(list(msgs))]
    return row


class AdminReportsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.moderation.view"

    @extend_schema(tags=["admin-moderation"])
    def get(self, request):
        qs = UserReport.objects.select_related("reporter", "reported", "message", "reviewed_by")
        st = request.query_params.get("status", "OPEN")
        if st in ReportStatus.values:
            qs = qs.filter(status=st)
        return paginated(self, request, qs, report_row)


class AdminReportDetailView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permissions = {"GET": "admin.moderation.view", "POST": "admin.moderation.manage"}

    class Input(serializers.Serializer):
        action = serializers.ChoiceField(choices=["DISMISS", "WARN", "HIDE_MESSAGE", "FREEZE"])
        note = serializers.CharField(min_length=5, max_length=1000)

    @extend_schema(tags=["admin-moderation"])
    def get(self, request, pk):
        r = get_object_or_404(UserReport.objects.select_related("reporter", "reported", "message", "conversation"),
                              pk=pk)
        return ok(report_row(r, detail=True))

    @extend_schema(tags=["admin-moderation"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        r = services.resolve_report(pk, request.user, action=d["action"], note=d["note"], request=request)
        return ok(report_row(r, detail=True))


class AdminSupportChatsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.support.chat"

    @extend_schema(tags=["admin-moderation"])
    def get(self, request):
        qs = Conversation.objects.filter(kind="SUPPORT").prefetch_related("participants__user")
        return ok([{
            "id": c.pk, "customer": next((p.user.full_name for p in c.participants.all() if p.user.role != "ADMIN"),
                                         "Customer"),
            "last_message_at": c.last_message_at,
            "last_message": (c.messages.order_by("-created_at").values_list("body", flat=True).first() or "")[:120],
        } for c in qs[:100]])
