"""
Deposits, withdrawals and transfers. Every movement posts a balanced journal
entry; every charge is computed by apps.commissions and shown to the user
before they confirm (see quote_fee).
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounting import services as ledger
from apps.accounting.models import AccountKind, EntryKind
from apps.audit import services as audit
from apps.commissions import calculators as fees
from apps.commissions.services import rules
from apps.common.exceptions import BusinessRuleViolation
from apps.common.money import quantize_money

from .models import Direction, IntentStatus, PaymentIntent, Purpose
from .providers import ProviderError, ProviderNotConfigured, get_provider

CLEARING = {"SANDBOX": AccountKind.CLEARING_SANDBOX, "MPESA": AccountKind.CLEARING_MPESA,
            "BANK": AccountKind.CLEARING_BANK, "INTASEND": AccountKind.CLEARING_GATEWAY,
            "PESAPAL": AccountKind.CLEARING_GATEWAY, "PAYSTACK": AccountKind.CLEARING_GATEWAY}
# Providers that ask the customer for a phone number (STK push prompts to it).
PHONE_PROVIDERS = {"MPESA", "INTASEND"}
# Only these can pay money out. Card and checkout providers take deposits only.
PAYOUT_PROVIDERS = {"MPESA", "SANDBOX"}


def _notify(user, kind, title, body, link=""):
    from apps.notifications.services import notify

    notify(user, kind, title, body, link)


def quote_fee(kind, amount):
    """What a deposit/withdrawal/transfer will cost, before the user confirms."""
    amount = quantize_money(amount)
    fee = fees.fee_for(kind, amount, rules())
    if kind == "deposit":
        return {"amount": amount, "fee": fee, "you_receive": amount - fee, "total_charged": amount}
    return {"amount": amount, "fee": fee, "you_receive": amount, "total_charged": amount + fee}


def _check_range(amount, low, high, what):
    if amount < Decimal(low):
        raise BusinessRuleViolation(f"The smallest {what} is KES {Decimal(low):,.2f}.", code="below_minimum")
    if Decimal(high) > 0 and amount > Decimal(high):
        raise BusinessRuleViolation(f"The largest {what} is KES {Decimal(high):,.2f}.", code="above_maximum")


def _existing(user, key):
    return PaymentIntent.objects.filter(user=user, idempotency_key=key).first() if key else None


# --- Deposits -----------------------------------------------------------------------------

@transaction.atomic
def start_deposit(user, *, amount, provider, phone_number="", purpose=Purpose.DEPOSIT, loan=None,
                  idempotency_key="", request=None):
    if existing := _existing(user, idempotency_key):
        return existing
    amount = quantize_money(amount)
    limits = rules()["limits"]
    _check_range(amount, limits["min_deposit"], limits["max_deposit"], "deposit")
    fee = fees.fee_for("deposit", amount, rules())
    if fee >= amount:
        raise BusinessRuleViolation("The deposit is smaller than its fee.", code="below_fee")
    if provider in PHONE_PROVIDERS and not phone_number:
        phone_number = user.phone_number or ""
        if not phone_number:
            raise BusinessRuleViolation("Add a phone number to deposit by M-Pesa.", code="no_phone")
    intent = PaymentIntent.objects.create(
        user=user, direction=Direction.IN, purpose=purpose, provider=provider, amount=amount, fee=fee,
        phone_number=phone_number, loan=loan, idempotency_key=idempotency_key,
    )
    try:
        intent.provider_reference = get_provider(provider).start_collection(intent)
    except (ProviderNotConfigured, ProviderError) as exc:
        raise BusinessRuleViolation(str(exc), code="provider_unavailable") from exc
    intent.save(update_fields=["provider_reference", "checkout_url", "updated_at"])
    audit.record(action="payment.deposit_started", entity_type="PaymentIntent", entity_id=intent.pk, actor=user,
                 after={"amount": amount, "provider": provider, "purpose": purpose}, request=request)
    return intent


@transaction.atomic
def settle(provider_reference, *, succeeded, raw=None, message="", actor=None, amount=None):
    """
    Called when the provider confirms or fails a payment (callback, or sandbox
    confirmation). Idempotent: a second confirmation for the same reference does nothing.
    """
    intent = PaymentIntent.objects.select_for_update().filter(provider_reference=provider_reference).first()
    if intent is None:
        raise BusinessRuleViolation("Unknown payment reference.", code="unknown_payment")
    if intent.is_final:
        return intent
    intent.raw_callback = raw
    if intent.direction == Direction.IN:
        return _settle_deposit(intent, succeeded, message, actor, amount)
    return _settle_payout(intent, succeeded, message, actor)


def _settle_deposit(intent, succeeded, message, actor, amount):
    if succeeded and amount is not None and quantize_money(amount) != intent.amount:
        succeeded, message = False, f"Amount mismatch: expected {intent.amount}, provider reported {amount}"
    if not succeeded:
        intent.status = IntentStatus.FAILED
        intent.failure_reason = message[:255] or "The payment wasn't completed."
        intent.save()
        _notify(intent.user, "deposit_failed", "Deposit not completed",
                f"Your deposit of KES {intent.amount:,.2f} wasn't completed: {intent.failure_reason}", "#/wallet")
        return intent
    entry = ledger.post(
        EntryKind.DEPOSIT, f"Deposit via {intent.get_provider_display()}",
        [ledger.Line(ledger.platform(CLEARING[intent.provider]), "DEBIT", intent.amount, "Money received"),
         ledger.Line(ledger.wallet(intent.user), "CREDIT", intent.amount - intent.fee, "Deposit"),
         ledger.Line(ledger.platform(AccountKind.REVENUE_DEPOSIT_FEE), "CREDIT", intent.fee, "Deposit fee")],
        external_reference=intent.provider_reference, idempotency_key=f"deposit-{intent.pk}", initiated_by=actor,
        loan=intent.loan,
    )
    intent.settle_entry = entry
    intent.status = IntentStatus.SUCCEEDED
    intent.save()
    _notify(intent.user, "deposit_confirmed", "Deposit received",
            f"KES {intent.amount - intent.fee:,.2f} is now in your wallet.", "#/wallet")
    if intent.purpose == Purpose.REPAYMENT and intent.loan_id:
        from apps.repayments.services import repay

        try:
            repay(intent.loan_id, intent.user, intent.amount - intent.fee, idempotency_key=f"intent-{intent.pk}")
        except BusinessRuleViolation as exc:
            _notify(intent.user, "repayment_failed", "Repayment not applied",
                    f"Your deposit arrived but couldn't be applied to the loan: {exc.detail}. It's in your wallet.",
                    "#/repayments")
    return intent


# --- Withdrawals -------------------------------------------------------------------------------

@transaction.atomic
def request_withdrawal(user, *, amount, provider, phone_number="", idempotency_key="", request=None):
    if existing := _existing(user, idempotency_key):
        return existing
    if provider not in PAYOUT_PROVIDERS:
        raise BusinessRuleViolation("Withdrawals are paid out by M-Pesa. Choose M-Pesa to withdraw.",
                                    code="provider_no_payout")
    amount = quantize_money(amount)
    r = rules()
    limits = r["limits"]
    _check_range(amount, limits["min_withdrawal"], limits["max_withdrawal"], "withdrawal")
    since = timezone.now() - timedelta(hours=24)
    today = (PaymentIntent.objects.filter(user=user, direction=Direction.OUT, created_at__gte=since)
             .exclude(status__in=[IntentStatus.FAILED, IntentStatus.REJECTED, IntentStatus.CANCELLED])
             .aggregate(t=Sum("amount"))["t"] or Decimal("0"))
    if today + amount > Decimal(limits["daily_withdrawal_limit"]):
        raise BusinessRuleViolation(
            f"That's over the daily withdrawal limit of KES {Decimal(limits['daily_withdrawal_limit']):,.2f}.",
            code="daily_limit")
    phone_number = phone_number or user.phone_number or ""
    if provider == "MPESA" and not (phone_number and user.is_phone_verified and phone_number == user.phone_number):
        raise BusinessRuleViolation("Withdrawals go to your verified phone number. Verify it first.",
                                    code="phone_unverified")
    fee = fees.fee_for("withdrawal", amount, r)
    intent = PaymentIntent.objects.create(
        user=user, direction=Direction.OUT, purpose=Purpose.WITHDRAWAL, provider=provider, amount=amount, fee=fee,
        phone_number=phone_number, idempotency_key=idempotency_key,
    )
    intent.request_entry = ledger.post(
        EntryKind.WITHDRAWAL_REQUEST, "Withdrawal requested",
        [ledger.Line(ledger.wallet(user), "DEBIT", amount + fee, "Withdrawal and fee"),
         ledger.Line(ledger.wallet(user, AccountKind.WALLET_PENDING), "CREDIT", amount, "Waiting to be paid out"),
         ledger.Line(ledger.platform(AccountKind.REVENUE_WITHDRAWAL_FEE), "CREDIT", fee, "Withdrawal fee")],
        idempotency_key=f"withdraw-{intent.pk}", initiated_by=user,
    )
    if amount >= Decimal(limits["withdrawal_approval_threshold"]):
        intent.status = IntentStatus.AWAITING_APPROVAL
        intent.save()
    else:
        intent.save()
        _start_payout(intent)
    audit.record(action="payment.withdrawal_requested", entity_type="PaymentIntent", entity_id=intent.pk,
                 actor=user, after={"amount": amount, "fee": fee, "status": intent.status}, request=request)
    return intent


def _start_payout(intent):
    try:
        intent.provider_reference = get_provider(intent.provider).start_payout(intent)
        intent.status = IntentStatus.PROCESSING
        intent.save()
    except (ProviderNotConfigured, ProviderError) as exc:
        _fail_payout(intent, str(exc))


def _fail_payout(intent, reason, status=IntentStatus.FAILED, actor=None):
    ledger.reverse(intent.request_entry, actor=actor, reason=reason[:120])
    intent.status = status
    intent.failure_reason = reason[:255]
    intent.save()
    _notify(intent.user, "withdrawal_failed", "Withdrawal returned to your wallet",
            f"Your withdrawal of KES {intent.amount:,.2f} wasn't paid out ({intent.failure_reason}). "
            "The amount and fee are back in your wallet.", "#/wallet")


def _settle_payout(intent, succeeded, message, actor):
    if intent.status != IntentStatus.PROCESSING:
        raise BusinessRuleViolation("This withdrawal isn't being paid out.", code="not_processing")
    if not succeeded:
        _fail_payout(intent, message or "The provider couldn't complete the payout.", actor=actor)
        return intent
    intent.settle_entry = ledger.post(
        EntryKind.WITHDRAWAL_PAID, f"Withdrawal paid via {intent.get_provider_display()}",
        [ledger.Line(ledger.wallet(intent.user, AccountKind.WALLET_PENDING), "DEBIT", intent.amount, "Paid out"),
         ledger.Line(ledger.platform(CLEARING[intent.provider]), "CREDIT", intent.amount, "Money sent")],
        external_reference=intent.provider_reference or "", idempotency_key=f"paid-{intent.pk}", initiated_by=actor,
    )
    intent.status = IntentStatus.SUCCEEDED
    intent.save()
    _notify(intent.user, "withdrawal_completed", "Withdrawal completed",
            f"KES {intent.amount:,.2f} has been sent to {intent.phone_number or 'your account'}.", "#/wallet")
    return intent


@transaction.atomic
def approve_withdrawal(intent_id, actor, request=None):
    intent = PaymentIntent.objects.select_for_update().get(pk=intent_id)
    if intent.status != IntentStatus.AWAITING_APPROVAL:
        raise BusinessRuleViolation("This withdrawal isn't waiting for approval.", code="not_awaiting")
    if intent.user_id == actor.pk:
        raise BusinessRuleViolation("You can't approve your own withdrawal.", code="self_action")
    intent.approved_by, intent.approved_at = actor, timezone.now()
    intent.save()
    _start_payout(intent)
    audit.record(action="payment.withdrawal_approved", entity_type="PaymentIntent", entity_id=intent.pk,
                 actor=actor, after={"status": intent.status}, request=request)
    return intent


@transaction.atomic
def reject_withdrawal(intent_id, actor, reason, request=None):
    intent = PaymentIntent.objects.select_for_update().get(pk=intent_id)
    if intent.status != IntentStatus.AWAITING_APPROVAL:
        raise BusinessRuleViolation("This withdrawal isn't waiting for approval.", code="not_awaiting")
    _fail_payout(intent, reason, status=IntentStatus.REJECTED, actor=actor)
    audit.record(action="payment.withdrawal_rejected", entity_type="PaymentIntent", entity_id=intent.pk,
                 actor=actor, reason=reason, request=request)
    return intent


@transaction.atomic
def cancel_intent(intent_id, user):
    intent = PaymentIntent.objects.select_for_update().get(pk=intent_id, user=user)
    if intent.direction == Direction.IN and intent.status == IntentStatus.PENDING:
        intent.status = IntentStatus.CANCELLED
        intent.save()
        return intent
    if intent.direction == Direction.OUT and intent.status == IntentStatus.AWAITING_APPROVAL:
        _fail_payout(intent, "Cancelled by you", status=IntentStatus.CANCELLED, actor=user)
        return intent
    raise BusinessRuleViolation("This payment can't be cancelled any more.", code="not_cancellable")


# --- Transfers and holds -------------------------------------------------------------------------

@transaction.atomic
def transfer(sender, *, recipient_email, amount, note="", idempotency_key="", request=None):
    from apps.accounts.models import User

    amount = quantize_money(amount)
    recipient = User.objects.filter(email__iexact=recipient_email.strip(), is_active=True).first()
    if recipient is None or recipient.role == "ADMIN":
        raise BusinessRuleViolation("There's no customer account with that email.", code="recipient_not_found")
    if recipient.pk == sender.pk:
        raise BusinessRuleViolation("You can't transfer to yourself.", code="self_transfer")
    if recipient.is_frozen:
        raise BusinessRuleViolation("That account can't receive transfers right now.", code="recipient_frozen")
    if amount < Decimal(rules()["limits"]["min_transfer"]):
        raise BusinessRuleViolation(f"The smallest transfer is KES {Decimal(rules()['limits']['min_transfer']):,.2f}.",
                                    code="below_minimum")
    fee = fees.fee_for("transfer", amount, rules())
    entry = ledger.post(
        EntryKind.TRANSFER, f"Transfer from {sender.email} to {recipient.email}",
        [ledger.Line(ledger.wallet(sender), "DEBIT", amount + fee, f"Transfer to {recipient.full_name}"),
         ledger.Line(ledger.wallet(recipient), "CREDIT", amount, f"Transfer from {sender.full_name}"),
         ledger.Line(ledger.platform(AccountKind.REVENUE_TRANSFER_FEE), "CREDIT", fee, "Transfer fee")],
        idempotency_key=f"transfer-{sender.pk}-{idempotency_key}" if idempotency_key else None, initiated_by=sender,
    )
    _notify(recipient, "transfer_received", "Money received",
            f"{sender.full_name} sent you KES {amount:,.2f}{': ' + note if note else ''}.", "#/wallet")
    audit.record(action="payment.transfer", entity_type="JournalEntry", entity_id=entry.pk, actor=sender,
                 after={"to": recipient.email, "amount": amount, "fee": fee}, request=request)
    return entry


@transaction.atomic
def hold_funds(*, actor, user, amount, reason, release=False, request=None):
    """Move money between a user's available and held balances (admin action, audited)."""
    amount = quantize_money(amount)
    src, dst = (AccountKind.WALLET_FROZEN, AccountKind.WALLET_AVAILABLE) if release else \
        (AccountKind.WALLET_AVAILABLE, AccountKind.WALLET_FROZEN)
    entry = ledger.post(
        EntryKind.RELEASE if release else EntryKind.HOLD, reason,
        [ledger.Line(ledger.wallet(user, src), "DEBIT", amount, reason),
         ledger.Line(ledger.wallet(user, dst), "CREDIT", amount, reason)],
        initiated_by=actor,
    )
    audit.record(action="wallet.released" if release else "wallet.held", entity_type="User", entity_id=user.pk,
                 actor=actor, after={"amount": amount}, reason=reason, request=request)
    return entry
