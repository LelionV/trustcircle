"""Staff: extensions, defaults and guarantor claims."""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.common.api import AmountField, ok, paginated, validated
from apps.common.permissions import HasPlatformPermission

from . import services
from .models import ExtensionRequest, ExtensionStatus


def extension_row(e):
    votes = list(e.votes.all())
    return {
        "id": e.pk, "loan_id": e.loan_id, "loan": e.loan.reference, "loan_status": e.loan.status,
        "borrower": e.loan.borrower.full_name, "days": e.days, "reason": e.reason, "status": e.status,
        "status_label": e.get_status_display(), "remaining_principal": e.remaining_principal,
        "extension_interest": e.extension_interest, "extension_fee": e.extension_fee,
        "after_missed_payment": e.after_missed_payment, "extensions_so_far": e.loan.extension_count,
        "consent_mode": e.rules_snapshot.get("investor_consent"), "consent_deadline": e.consent_deadline,
        "votes": {"agree": sum(1 for v in votes if v.agrees), "object": sum(1 for v in votes if not v.agrees)},
        "decision_reason": e.decision_reason, "reviewed_by": e.reviewed_by.email if e.reviewed_by_id else None,
        "created_at": e.created_at, "trust_score": e.loan.trust_score_snapshot,
    }


class AdminExtensionsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.extensions.review"

    @extend_schema(tags=["admin-loans"])
    def get(self, request):
        qs = ExtensionRequest.objects.select_related("loan", "loan__borrower", "reviewed_by").prefetch_related("votes")
        st = request.query_params.get("status", "REQUESTED")
        if st in ExtensionStatus.values:
            qs = qs.filter(status=st)
        return paginated(self, request, qs, extension_row)


class AdminExtensionDecisionView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.extensions.review"

    class Input(serializers.Serializer):
        approve = serializers.BooleanField()
        reason = serializers.CharField(min_length=5, max_length=1000)

    @extend_schema(tags=["admin-loans"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        ext = services.review_extension(pk, request.user, approve=d["approve"], reason=d["reason"], request=request)
        ext.refresh_from_db()
        return ok(extension_row(ext))


def claim_row(c):
    g = c.guarantee
    return {"id": c.pk, "loan": g.loan.reference, "loan_id": g.loan_id, "guarantor": g.guarantor.full_name,
            "guarantor_email": g.guarantor.email, "amount": c.amount, "recovered": c.recovered,
            "outstanding": c.outstanding, "reimbursed": c.reimbursed, "status": c.status,
            "status_label": c.get_status_display(), "note": c.note, "created_at": c.created_at}


class AdminDefaultsView(APIView):
    """Overdue and defaulted loans, and guarantor claims."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.defaults.manage"

    @extend_schema(tags=["admin-loans"])
    def get(self, request):
        from django.utils import timezone

        from apps.guarantors.models import GuaranteeClaim
        from apps.loans.models import Loan

        today = timezone.localdate()
        loans = []
        for l in Loan.objects.filter(status__in=["OVERDUE", "DEFAULTED"]).select_related("borrower"):
            out = services.outstanding(l)
            loans.append({"id": l.pk, "reference": l.reference, "status": l.status,
                          "status_label": l.get_status_display(), "borrower": l.borrower.full_name,
                          "borrower_email": l.borrower.email, "amount": l.amount,
                          "overdue_since": l.overdue_since,
                          "days_overdue": (today - l.overdue_since).days if l.overdue_since else None,
                          "outstanding": out["total"], "late_fees": out["late_fee"],
                          "defaulted_at": l.defaulted_at})
        claims = GuaranteeClaim.objects.select_related("guarantee__loan", "guarantee__guarantor")
        return ok({"loans": loans, "claims": [claim_row(c) for c in claims[:200]]})


class AdminMarkDefaultView(APIView):
    """Declare an overdue loan in default before the automatic cut-off (audited)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.defaults.manage"

    class Input(serializers.Serializer):
        reason = serializers.CharField(min_length=10, max_length=500)

    @extend_schema(tags=["admin-loans"], request=Input)
    def post(self, request, pk):
        from django.db import transaction

        from apps.common.exceptions import BusinessRuleViolation

        d = validated(self.Input, request.data)
        with transaction.atomic():
            loan = services._lock_loan(pk)
            if loan.status != "OVERDUE":
                raise BusinessRuleViolation("Only overdue loans can be put into default.", code="not_overdue")
            services.default_loan(loan, reason=d["reason"], actor=request.user)
        return ok({"status": "DEFAULTED"})


class AdminClaimView(APIView):
    """POST {action: COLLECT [amount]} or {action: WRITE_OFF, reason}."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.defaults.manage"

    class Input(serializers.Serializer):
        action = serializers.ChoiceField(choices=["COLLECT", "WRITE_OFF"])
        amount = AmountField(required=False)
        reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    @extend_schema(tags=["admin-loans"], request=Input)
    def post(self, request, pk):
        from apps.common.exceptions import BusinessRuleViolation
        from apps.guarantors.models import GuaranteeClaim

        d = validated(self.Input, request.data)
        get_object_or_404(GuaranteeClaim, pk=pk)
        if d["action"] == "COLLECT":
            claim = services.collect_claim(pk, actor=request.user, amount=d.get("amount"), request=request)
        else:
            if len(d["reason"]) < 10:
                raise BusinessRuleViolation("Explain why the claim is written off.", code="reason_required")
            claim = services.write_off_claim(pk, request.user, d["reason"], request=request)
        return ok(claim_row(claim))
