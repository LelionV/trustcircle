from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.common.api import ok, validated
from apps.common.permissions import HasPlatformPermission

from . import services
from .models import Guarantee


def guarantee_row(g):
    loan = g.loan
    claim = getattr(g, "claim", None)
    return {
        "id": g.pk, "status": g.status, "status_label": g.get_status_display(), "loan_id": loan.pk,
        "loan": loan.reference, "loan_status": loan.status, "loan_status_label": loan.get_status_display(),
        "borrower": loan.borrower.full_name, "amount": loan.amount, "term_months": loan.term_months,
        "rate": loan.annual_rate, "rate_basis": loan.rate_basis, "trust_score": loan.trust_score_snapshot,
        "risk_class": loan.risk_class_snapshot, "purpose": loan.get_purpose_display(),
        "coverage_amount": g.coverage_amount, "interest_to_lock": services.interest_to_lock(loan),
        "locked_amount": g.locked_amount, "lock_released_at": g.lock_released_at,
        "commission_earned": g.commission_earned, "responded_at": g.responded_at, "note": g.response_note,
        "can_accept": g.status == "REQUESTED" and services.can_accept(loan),
        "created_at": g.created_at,
        "claim": None if claim is None else {
            "amount": claim.amount, "recovered": claim.recovered, "outstanding": claim.outstanding,
            "reimbursed": claim.reimbursed, "status": claim.status, "status_label": claim.get_status_display()},
    }


class MyGuaranteesView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "guarantees.view_own"

    @extend_schema(tags=["guarantees"])
    def get(self, request):
        services.backfill_requests(request.user)  # loans that named you before requests were sent at submission
        qs = Guarantee.objects.filter(guarantor=request.user).select_related("loan", "loan__borrower")
        rows = [guarantee_row(g) for g in qs]
        return ok({
            "guarantees": rows,
            "exposure": services.exposure(request.user),
            "commission_total": sum((g.commission_earned for g in qs), 0),
        })


class GuaranteeRespondView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "guarantees.respond"

    class Input(serializers.Serializer):
        accept = serializers.BooleanField()
        note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    @extend_schema(tags=["guarantees"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        g = services.respond(pk, request.user, accept=d["accept"], note=d["note"], request=request)
        return ok(guarantee_row(g))


class GuaranteeWithdrawView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "guarantees.respond"

    class Input(serializers.Serializer):
        note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    @extend_schema(tags=["guarantees"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        return ok(guarantee_row(services.withdraw(pk, request.user, d["note"], request=request)))


class GuaranteeClaimPayView(APIView):
    """A guarantor pays towards a claim from their wallet (top up first if needed)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "guarantees.view_own"

    @extend_schema(tags=["guarantees"], request=None)
    def post(self, request, pk):
        from apps.repayments.services import collect_claim

        g = Guarantee.objects.select_related("loan", "loan__borrower").get(pk=pk, guarantor=request.user)
        if hasattr(g, "claim"):
            collect_claim(g.claim.pk, actor=request.user, request=request)
            g.refresh_from_db()
        return ok(guarantee_row(g))
