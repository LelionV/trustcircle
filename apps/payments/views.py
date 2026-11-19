"""
Wallet and payment endpoints.

Customers: balances, transactions, fee quotes, deposit, withdraw, transfer,
payment status, statement CSV, sandbox confirmation.
Providers: M-Pesa callbacks (STK push result, B2C result/timeout).
Staff: withdrawal approvals, wallet holds, payment list.
"""
import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.accounting import services as ledger
from apps.accounts.models import User
from apps.common.api import AmountField, IdempotentInput, csv_response, ok, paginated, validated
from apps.common.exceptions import BusinessRuleViolation
from apps.common.permissions import HasPlatformPermission
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from . import services
from .models import Direction, IntentStatus, PaymentIntent, Purpose
from .providers import MpesaProvider, ProviderError, ProviderNotConfigured, available_providers

log = logging.getLogger(__name__)


def intent_row(i, admin=False):
    row = {
        "id": i.pk, "direction": i.direction, "direction_label": i.get_direction_display(),
        "purpose": i.purpose, "purpose_label": i.get_purpose_display(), "provider": i.provider,
        "provider_label": i.get_provider_display(), "amount": i.amount, "fee": i.fee, "phone_number": i.phone_number,
        "status": i.status, "status_label": i.get_status_display(), "failure_reason": i.failure_reason,
        "provider_reference": i.provider_reference, "checkout_url": i.checkout_url,
        "loan": i.loan.reference if i.loan_id else None,
        "created_at": i.created_at, "updated_at": i.updated_at,
        "can_confirm_in_sandbox": i.provider == "SANDBOX" and not i.is_final and
        i.status in (IntentStatus.PENDING, IntentStatus.PROCESSING),
    }
    if admin:
        row["user"] = {"id": i.user_id, "name": i.user.full_name, "email": i.user.email}
        row["approved_by"] = i.approved_by.email if i.approved_by_id else None
    return row


def line_row(l):
    return {
        "id": l.pk, "at": l.entry.created_at, "reference": l.entry.reference, "kind": l.entry.kind,
        "kind_label": l.entry.get_kind_display(), "account": l.account.kind,
        "account_label": l.account.get_kind_display(), "side": l.side,
        "amount": l.amount if l.side == "CREDIT" else -l.amount, "memo": l.memo or l.entry.description,
        "balance_after": l.balance_after, "loan": l.entry.loan.reference if l.entry.loan_id else None,
    }


class GatewayWebhookView(APIView):
    """
    Callbacks from IntaSend, Pesapal and Paystack. No login: each request is
    checked (challenge, signature or a status lookup with the provider) before
    any money moves. Unknown or unverifiable requests get a 403.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(exclude=True)
    def get(self, request, provider):
        return self._handle(request, provider)

    @extend_schema(exclude=True)
    def post(self, request, provider):
        return self._handle(request, provider)

    @staticmethod
    def _handle(request, provider):
        from .gateways import WebhookRejected, handle_webhook

        try:
            return Response(handle_webhook(provider.lower(), request))
        except WebhookRejected as exc:
            log.warning("Rejected %s webhook: %s", provider, exc)
            return Response({"detail": str(exc)}, status=403)
        except ProviderNotConfigured:
            return Response({"detail": "This payment provider isn't switched on."}, status=403)
        except ProviderError as exc:
            log.warning("Could not verify %s webhook: %s", provider, exc)
            return Response({"detail": "Could not verify the payment with the provider."}, status=502)


class WalletView(APIView):
    """Balances, available payment methods and the current fee rules."""

    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.view_own"

    @extend_schema(tags=["wallet"])
    def get(self, request):
        from apps.commissions.services import rules

        r = rules()
        b = ledger.balances(request.user)
        return ok({
            "balances": {**b, "total": sum(b.values())},
            "providers": available_providers(),
            "sandbox": getattr(settings, "SANDBOX_PAYMENTS_ENABLED", False),
            "fees": r["fees"], "limits": r["limits"],
            "pending_payments": PaymentIntent.objects.filter(
                user=request.user, status__in=[IntentStatus.PENDING, IntentStatus.PROCESSING,
                                               IntentStatus.AWAITING_APPROVAL]).count(),
        })


class TransactionsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.view_own"

    @extend_schema(tags=["wallet"])
    def get(self, request):
        qs = ledger.user_lines(request.user).select_related("entry__loan")
        account = request.query_params.get("account")
        if account:
            qs = qs.filter(account__kind=account)
        return paginated(self, request, qs, line_row)


class StatementCsvView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.view_own"

    @extend_schema(tags=["wallet"])
    def get(self, request):
        from apps.reports.services import parse_date, statement_csv

        start, end = parse_date(request.query_params.get("start")), parse_date(request.query_params.get("end"))
        return csv_response(statement_csv(request.user, start, end), "statement.csv")


class FeeQuoteView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.view_own"

    class Input(serializers.Serializer):
        kind = serializers.ChoiceField(choices=["deposit", "withdrawal", "transfer"])
        amount = AmountField()

    @extend_schema(tags=["wallet"], request=Input)
    def post(self, request):
        d = validated(self.Input, request.data)
        return ok(services.quote_fee(d["kind"], d["amount"]))


class PaymentsView(APIView):
    """GET your payments (deposits and withdrawals)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.view_own"

    @extend_schema(tags=["wallet"])
    def get(self, request):
        qs = PaymentIntent.objects.filter(user=request.user).select_related("loan")
        return paginated(self, request, qs, intent_row)


class PaymentDetailView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.view_own"

    @extend_schema(tags=["wallet"])
    def get(self, request, pk):
        return ok(intent_row(get_object_or_404(PaymentIntent, pk=pk, user=request.user)))


class PaymentCancelView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.view_own"

    @extend_schema(tags=["wallet"], request=None)
    def post(self, request, pk):
        return ok(intent_row(services.cancel_intent(pk, request.user)))


class DepositView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.deposit"

    class Input(IdempotentInput):
        amount = AmountField()
        provider = serializers.ChoiceField(choices=["SANDBOX", "MPESA", "BANK"])
        phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
        loan_id = serializers.UUIDField(required=False, allow_null=True,
                                        help_text="Set to repay a loan straight from this deposit.")

    @extend_schema(tags=["wallet"], request=Input)
    def post(self, request):
        from apps.common.phone import normalize_phone
        from apps.loans.models import Loan

        d = validated(self.Input, request.data)
        loan = None
        if d.get("loan_id"):
            loan = get_object_or_404(Loan, pk=d["loan_id"], borrower=request.user)
        phone = d["phone_number"]
        if phone:
            try:
                phone = normalize_phone(phone)
            except Exception as exc:  # noqa: BLE001
                raise BusinessRuleViolation("Enter a valid Kenyan phone number.", code="invalid_phone") from exc
        intent = services.start_deposit(
            request.user, amount=d["amount"], provider=d["provider"], phone_number=phone,
            purpose=Purpose.REPAYMENT if loan else Purpose.DEPOSIT, loan=loan,
            idempotency_key=d["idempotency_key"], request=request)
        return ok(intent_row(intent), status=201)


class WithdrawView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.withdraw"

    class Input(IdempotentInput):
        amount = AmountField()
        provider = serializers.ChoiceField(choices=["SANDBOX", "MPESA", "BANK"])

    @extend_schema(tags=["wallet"], request=Input)
    def post(self, request):
        d = validated(self.Input, request.data)
        intent = services.request_withdrawal(request.user, amount=d["amount"], provider=d["provider"],
                                             idempotency_key=d["idempotency_key"], request=request)
        return ok(intent_row(intent), status=201)


class TransferView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.transfer"

    class Input(IdempotentInput):
        recipient_email = serializers.EmailField()
        amount = AmountField()
        note = serializers.CharField(max_length=140, required=False, allow_blank=True, default="")

    @extend_schema(tags=["wallet"], request=Input)
    def post(self, request):
        d = validated(self.Input, request.data)
        entry = services.transfer(request.user, recipient_email=d["recipient_email"], amount=d["amount"],
                                  note=d["note"], idempotency_key=d["idempotency_key"], request=request)
        return ok({"reference": entry.reference, "balances": ledger.balances(request.user)}, status=201)


class SandboxConfirmView(APIView):
    """
    Development only: act as the payment provider and confirm (or fail) one of
    YOUR OWN sandbox payments, as if you'd entered your M-Pesa PIN.
    """

    permission_classes = [HasPlatformPermission]
    required_permission = "wallet.view_own"

    class Input(serializers.Serializer):
        succeed = serializers.BooleanField(default=True)

    @extend_schema(tags=["wallet"], request=Input)
    def post(self, request, pk):
        if not getattr(settings, "SANDBOX_PAYMENTS_ENABLED", False):
            raise BusinessRuleViolation("Sandbox payments are switched off on this server.", code="sandbox_off")
        intent = get_object_or_404(PaymentIntent, pk=pk, user=request.user, provider="SANDBOX")
        d = validated(self.Input, request.data)
        if not intent.provider_reference:
            raise BusinessRuleViolation("This payment hasn't been sent to the provider.", code="not_started")
        intent = services.settle(intent.provider_reference, succeeded=d["succeed"],
                                 message="" if d["succeed"] else "Declined in the sandbox",
                                 raw={"sandbox": True, "by": str(request.user.pk)}, amount=intent.amount)
        return ok({**intent_row(intent), "balances": ledger.balances(request.user)})


# --- M-Pesa callbacks ---------------------------------------------------------------------

class _MpesaCallback(APIView):
    """Daraja posts here. Guarded by a secret token in the URL (MPESA_CALLBACK_TOKEN)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def _check(self, request):
        expected = settings.MPESA.get("CALLBACK_TOKEN", "")
        return bool(expected) and request.query_params.get("token") == expected

    def _ack(self):
        return ok({"ResultCode": 0, "ResultDesc": "Accepted"})


class MpesaStkCallbackView(_MpesaCallback):
    @extend_schema(exclude=True)
    def post(self, request):
        if not self._check(request):
            log.warning("Rejected M-Pesa callback with a bad token")
            return ok({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)
        try:
            ref, succeeded, amount, message = MpesaProvider.parse_stk_callback(request.data)
            services.settle(ref, succeeded=succeeded, raw=request.data, message=message, amount=amount)
        except BusinessRuleViolation as exc:
            log.warning("M-Pesa STK callback not applied: %s", exc.detail)
        except (KeyError, TypeError, ValueError):
            log.exception("Malformed M-Pesa STK callback")
        return self._ack()


class MpesaB2cResultView(_MpesaCallback):
    @extend_schema(exclude=True)
    def post(self, request):
        if not self._check(request):
            return ok({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)
        try:
            ref, succeeded, message = MpesaProvider.parse_b2c_result(request.data)
            services.settle(ref, succeeded=succeeded, raw=request.data, message=message)
        except BusinessRuleViolation as exc:
            log.warning("M-Pesa B2C result not applied: %s", exc.detail)
        except (KeyError, TypeError, ValueError):
            log.exception("Malformed M-Pesa B2C result")
        return self._ack()


class MpesaB2cTimeoutView(_MpesaCallback):
    """A timeout doesn't mean the payout failed; leave it PROCESSING for staff to check."""

    @extend_schema(exclude=True)
    def post(self, request):
        if self._check(request):
            log.warning("M-Pesa B2C timeout: %s", request.data)
        return self._ack()


# --- Staff ------------------------------------------------------------------------------------

class AdminPaymentsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.wallets.view"

    @extend_schema(tags=["admin-finance"])
    def get(self, request):
        qs = PaymentIntent.objects.select_related("user", "loan", "approved_by")
        st = request.query_params.get("status")
        if st in IntentStatus.values:
            qs = qs.filter(status=st)
        direction = request.query_params.get("direction")
        if direction in Direction.values:
            qs = qs.filter(direction=direction)
        return paginated(self, request, qs, lambda i: intent_row(i, admin=True))


class AdminWithdrawalDecisionView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.withdrawals.approve"

    class Input(serializers.Serializer):
        approve = serializers.BooleanField()
        reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    @extend_schema(tags=["admin-finance"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        if d["approve"]:
            intent = services.approve_withdrawal(pk, request.user, request=request)
        else:
            if len(d["reason"]) < 5:
                raise BusinessRuleViolation("Give a reason the customer will see.", code="reason_required")
            intent = services.reject_withdrawal(pk, request.user, d["reason"], request=request)
        return ok(intent_row(intent, admin=True))


class AdminWalletView(APIView):
    """A customer's balances and recent lines; POST to hold or release funds."""

    permission_classes = [HasPlatformPermission]
    required_permissions = {"GET": "admin.wallets.view", "POST": "admin.wallets.hold"}

    class Input(serializers.Serializer):
        amount = AmountField()
        release = serializers.BooleanField(default=False)
        reason = serializers.CharField(min_length=5, max_length=255)

    @extend_schema(tags=["admin-finance"])
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        lines = ledger.user_lines(user).select_related("entry__loan")[:50]
        return ok({"balances": ledger.balances(user), "lines": [line_row(l) for l in lines]})

    @extend_schema(tags=["admin-finance"], request=Input)
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        d = validated(self.Input, request.data)
        services.hold_funds(actor=request.user, user=user, amount=d["amount"], reason=d["reason"],
                            release=d["release"], request=request)
        return ok({"balances": ledger.balances(user)})
