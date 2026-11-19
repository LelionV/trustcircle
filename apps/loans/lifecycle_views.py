"""
Loan life after approval: agreement, guarantor changes, offers on the
borrower's own loan, repayments, extensions, and the staff pay-out action.
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.common.api import AmountField, IdempotentInput, ok, paginated, validated
from apps.common.permissions import HasPlatformPermission

from . import agreements
from .models import Loan
from .serializers import AdminLoanSerializer, LoanSerializer


def _mine(request, pk):
    return get_object_or_404(Loan.objects.select_related("product", "borrower"), pk=pk, borrower=request.user)


def _loan_payload(request, loan):
    loan.refresh_from_db()
    return LoanSerializer(loan, context={"request": request}).data


class AgreementView(APIView):
    """GET the current agreement; POST to accept it."""

    permission_classes = [HasPlatformPermission]
    required_permission = "loans.view_own"

    @extend_schema(tags=["loans"])
    def get(self, request, pk):
        loan = _mine(request, pk)
        a = agreements.current(loan)
        if a is None:
            return ok(None)
        return ok({"version": a.version, "text": a.text, "terms": a.terms, "accepted_at": a.accepted_at})

    @extend_schema(tags=["loans"], request=None)
    def post(self, request, pk):
        loan = _mine(request, pk)
        agreements.accept(loan, request.user, request=request)
        return ok(_loan_payload(request, loan))


class RenominateGuarantorView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "loans.apply"

    class Input(serializers.Serializer):
        guarantor_email = serializers.EmailField()

    @extend_schema(tags=["loans"], request=Input)
    def post(self, request, pk):
        from apps.guarantors.services import renominate

        d = validated(self.Input, request.data)
        renominate(pk, request.user, d["guarantor_email"], request=request)
        return ok(_loan_payload(request, _mine(request, pk)))


class OfferDecisionView(APIView):
    """The borrower accepts or declines an offer on their open-offers loan."""

    permission_classes = [HasPlatformPermission]
    required_permission = "loans.view_own"

    class Input(serializers.Serializer):
        accept = serializers.BooleanField()
        reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    @extend_schema(tags=["loans"], request=Input)
    def post(self, request, pk, offer_id):
        from apps.investments import offers

        loan = _mine(request, pk)
        d = validated(self.Input, request.data)
        if d["accept"]:
            offers.accept_offer(offer_id, request.user, request=request)
        else:
            offers.decline_offer(offer_id, request.user, d["reason"])
        return ok(_loan_payload(request, loan))


class RepayView(APIView):
    """Pay from your wallet balance. (To pay by M-Pesa, deposit with loan_id set.)"""

    permission_classes = [HasPlatformPermission]
    required_permission = "repayments.make"

    class Input(IdempotentInput):
        amount = AmountField()

    @extend_schema(tags=["repayments"], request=Input)
    def post(self, request, pk):
        from apps.repayments.services import repay

        loan = _mine(request, pk)
        d = validated(self.Input, request.data)
        r = repay(loan.pk, request.user, d["amount"], idempotency_key=d["idempotency_key"], request=request)
        return ok({"repayment": repayment_row(r), "loan": _loan_payload(request, loan)}, status=201)


def repayment_row(r):
    return {"id": r.pk, "loan": r.loan.reference, "loan_id": r.loan_id, "amount": r.amount,
            "principal": r.principal, "interest": r.interest, "extension_interest": r.extension_interest,
            "extension_fee": r.extension_fee, "late_fee": r.late_fee, "allocation": r.allocation,
            "reference": r.entry.reference, "created_at": r.created_at}


class MyRepaymentsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "loans.view_own"

    @extend_schema(tags=["repayments"])
    def get(self, request):
        from apps.repayments.models import Repayment

        qs = Repayment.objects.filter(payer=request.user).select_related("loan", "entry")
        loan = request.query_params.get("loan")
        if loan:
            qs = qs.filter(loan_id=loan)
        return paginated(self, request, qs, repayment_row)


class ExtensionView(APIView):
    """GET ?days=30 for a quote; POST to request."""

    permission_classes = [HasPlatformPermission]
    required_permissions = {"GET": "loans.view_own", "POST": "extensions.request"}

    class Input(serializers.Serializer):
        days = serializers.IntegerField(min_value=1, max_value=365)
        reason = serializers.CharField(min_length=10, max_length=1000)

    @extend_schema(tags=["extensions"])
    def get(self, request, pk):
        from apps.repayments.services import quote_extension

        loan = _mine(request, pk)
        try:
            days = int(request.query_params.get("days", 30))
        except ValueError:
            days = 30
        return ok(quote_extension(loan, days))

    @extend_schema(tags=["extensions"], request=Input)
    def post(self, request, pk):
        from apps.repayments.services import request_extension

        loan = _mine(request, pk)
        d = validated(self.Input, request.data)
        request_extension(loan.pk, request.user, d["days"], d["reason"], request=request)
        return ok(_loan_payload(request, loan), status=201)


class ExtensionCancelView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "extensions.request"

    @extend_schema(tags=["extensions"], request=None)
    def post(self, request, pk, ext_id):
        from apps.repayments.services import cancel_extension

        loan = _mine(request, pk)
        cancel_extension(ext_id, request.user)
        return ok(_loan_payload(request, loan))


# --- Staff -----------------------------------------------------------------------------------

class AdminDisburseView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.loans.disburse"

    @extend_schema(tags=["admin-loans"], request=None)
    def post(self, request, pk):
        from apps.investments.services import disburse

        loan = disburse(pk, request.user, request=request)
        return ok(AdminLoanSerializer(loan, context={"request": request}).data)


class AdminCancelFundingView(APIView):
    """Cancel a loan before pay-out, returning every investor's money."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.loans.approve"

    class Input(serializers.Serializer):
        reason = serializers.CharField(min_length=10, max_length=500)

    @extend_schema(tags=["admin-loans"], request=Input)
    def post(self, request, pk):
        from apps.investments.services import cancel_funding

        d = validated(self.Input, request.data)
        loan = cancel_funding(pk, actor=request.user, reason=d["reason"], request=request)
        return ok(AdminLoanSerializer(loan, context={"request": request}).data)
