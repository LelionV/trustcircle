"""Disputes: customers raise them; staff work them to a resolution."""
import secrets

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.common.api import ok, paginated, validated
from apps.common.exceptions import BusinessRuleViolation
from apps.common.permissions import HasPlatformPermission
from apps.notifications.services import notify, notify_admins

from .models import Dispute, DisputeCategory, DisputeStatus


def _reference():
    while True:
        ref = f"DS-{timezone.localdate():%y%m}-{secrets.token_hex(3).upper()}"
        if not Dispute.objects.filter(reference=ref).exists():
            return ref


def row(d, staff=False):
    r = {"id": d.pk, "reference": d.reference, "category": d.category, "category_label": d.get_category_display(),
         "subject": d.subject, "description": d.description, "loan": d.loan.reference if d.loan_id else None,
         "transaction_reference": d.transaction_reference, "status": d.status,
         "status_label": d.get_status_display(), "resolution": d.resolution, "resolved_at": d.resolved_at,
         "created_at": d.created_at, "updated_at": d.updated_at}
    if staff:
        r["raised_by"] = {"id": d.raised_by_id, "name": d.raised_by.full_name, "email": d.raised_by.email}
        r["assigned_to"] = d.assigned_to.email if d.assigned_to_id else None
    return r


class MyDisputesView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "disputes.raise"

    class Input(serializers.Serializer):
        category = serializers.ChoiceField(choices=DisputeCategory.choices)
        subject = serializers.CharField(min_length=5, max_length=120)
        description = serializers.CharField(min_length=20, max_length=4000)
        loan_reference = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
        transaction_reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")

    @extend_schema(tags=["disputes"])
    def get(self, request):
        return ok({"categories": [{"value": v, "label": l} for v, l in DisputeCategory.choices],
                   "disputes": [row(d) for d in Dispute.objects.filter(raised_by=request.user).select_related("loan")]})

    @extend_schema(tags=["disputes"], request=Input)
    def post(self, request):
        from django.db.models import Q

        from apps.loans.models import Loan

        d = validated(self.Input, request.data)
        loan = None
        if d["loan_reference"]:
            u = request.user
            loan = Loan.objects.filter(reference__iexact=d["loan_reference"].strip()).filter(
                Q(borrower=u) | Q(investments__investor=u) | Q(guarantees__guarantor=u)).distinct().first()
            if loan is None:
                raise BusinessRuleViolation("We couldn't find that loan on your account.", code="loan_not_found")
        dispute = Dispute.objects.create(reference=_reference(), raised_by=request.user, category=d["category"],
                                         subject=d["subject"], description=d["description"], loan=loan,
                                         transaction_reference=d["transaction_reference"])
        audit.record(action="dispute.raised", entity_type="Dispute", entity_id=dispute.pk, actor=request.user,
                     after={"reference": dispute.reference, "category": dispute.category}, request=request)
        notify_admins("admin.disputes.manage", "dispute_raised", "New dispute",
                      f"{dispute.reference}: {dispute.subject}", "#/admin/disputes")
        return ok(row(dispute), status=201)


class AdminDisputesView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.disputes.view"

    @extend_schema(tags=["admin-disputes"])
    def get(self, request):
        qs = Dispute.objects.select_related("raised_by", "loan", "assigned_to")
        st = request.query_params.get("status")
        if st in DisputeStatus.values:
            qs = qs.filter(status=st)
        return paginated(self, request, qs, lambda d: row(d, staff=True))


class AdminDisputeView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.disputes.manage"

    class Input(serializers.Serializer):
        status = serializers.ChoiceField(choices=DisputeStatus.choices)
        resolution = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")

    @extend_schema(tags=["admin-disputes"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        with transaction.atomic():
            dispute = get_object_or_404(Dispute.objects.select_for_update(), pk=pk)
            if dispute.raised_by_id == request.user.pk:
                raise BusinessRuleViolation("You can't handle your own dispute.", code="self_review")
            if d["status"] in (DisputeStatus.RESOLVED, DisputeStatus.REJECTED) and len(d["resolution"]) < 10:
                raise BusinessRuleViolation("Explain the outcome to the customer.", code="resolution_required")
            before = dispute.status
            dispute.status = d["status"]
            dispute.assigned_to = request.user
            if d["resolution"]:
                dispute.resolution = d["resolution"]
            if d["status"] in (DisputeStatus.RESOLVED, DisputeStatus.REJECTED):
                dispute.resolved_at = timezone.now()
            dispute.save()
            audit.record(action="dispute.updated", entity_type="Dispute", entity_id=dispute.pk, actor=request.user,
                         before={"status": before}, after={"status": dispute.status}, reason=d["resolution"],
                         request=request)
        notify(dispute.raised_by, "dispute_updated", f"Dispute {dispute.reference}: {dispute.get_status_display()}",
               dispute.resolution or "We're looking into it.", "#/disputes")
        return ok(row(dispute, staff=True))
