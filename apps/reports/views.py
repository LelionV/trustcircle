"""Staff: finance, ledger, reconciliation, reports, CSV exports, fees & limits, scheduled jobs."""
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.common.api import csv_response, ok, paginated, validated
from apps.common.exceptions import BusinessRuleViolation
from apps.common.permissions import HasPlatformPermission

from . import jobs, services


class MetricsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.reports.view"

    @extend_schema(tags=["admin-reports"])
    def get(self, request):
        start = services.parse_date(request.query_params.get("start"))
        end = services.parse_date(request.query_params.get("end"))
        return ok({"portfolio": services.portfolio_metrics(),
                   "finance": services.finance_summary(start, end),
                   "exports": [{"key": k, "label": v[0]} for k, v in services.EXPORTS.items()]})


class ExportView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.reports.view"

    @extend_schema(tags=["admin-reports"])
    def get(self, request, name):
        if name not in services.EXPORTS:
            raise BusinessRuleViolation("Unknown report.", code="unknown_report")
        fn = services.EXPORTS[name][1]
        start = services.parse_date(request.query_params.get("start"))
        end = services.parse_date(request.query_params.get("end"))
        text = fn() if name == "loans" else fn(start, end)
        from apps.audit import services as audit

        audit.record(action="report.exported", entity_type="Report", entity_id=name, actor=request.user,
                     after={"start": start, "end": end}, request=request)
        return csv_response(text, f"{name}.csv")


class ReconcileView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.reconciliation.run"

    @extend_schema(tags=["admin-finance"])
    def get(self, request):
        from apps.accounting.services import reconcile

        return ok(reconcile())


class RevenueView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.revenue.view"

    @extend_schema(tags=["admin-finance"])
    def get(self, request):
        from apps.accounting.services import revenue_by_category

        start = services.parse_date(request.query_params.get("start"))
        end = services.parse_date(request.query_params.get("end"))
        rev = revenue_by_category(start, end)
        return ok({"categories": rev, "total": sum((r["amount"] for r in rev.values()), 0)})


class LedgerEntriesView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.ledger.view"

    @extend_schema(tags=["admin-finance"])
    def get(self, request):
        from apps.accounting.models import JournalEntry

        qs = JournalEntry.objects.select_related("loan", "initiated_by").prefetch_related("lines__account__owner")
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        term = (request.query_params.get("search") or "").strip()
        if term:
            qs = qs.filter(reference__icontains=term) | qs.filter(external_reference__icontains=term)

        def row(e):
            return {"id": e.pk, "reference": e.reference, "kind": e.kind, "kind_label": e.get_kind_display(),
                    "description": e.description, "loan": e.loan.reference if e.loan_id else None,
                    "external_reference": e.external_reference, "created_at": e.created_at,
                    "by": e.initiated_by.email if e.initiated_by_id else "System",
                    "reverses": e.reverses_id, "lines": [
                        {"account": l.account.get_kind_display(),
                         "owner": l.account.owner.email if l.account.owner_id else "Platform",
                         "side": l.side, "amount": l.amount, "memo": l.memo} for l in e.lines.all()]}
        return paginated(self, request, qs, row)


class PlatformRulesView(APIView):
    """Fees, limits, revenue split, extension, overdue, offers and guarantee rules (versioned)."""

    permission_classes = [HasPlatformPermission]
    required_permissions = {"GET": "admin.dashboard.view", "PUT": "admin.config.manage"}

    class Input(serializers.Serializer):
        parameters = serializers.DictField()
        reason = serializers.CharField(min_length=10, max_length=1000)

    @extend_schema(tags=["configuration"])
    def get(self, request):
        from apps.commissions.models import PlatformRules
        from apps.commissions.services import active_rules, rules

        current = active_rules()
        return ok({"version": current.version, "parameters": rules(), "history": [
            {"version": v.version, "is_active": v.is_active, "reason": v.reason,
             "by": v.created_by.email if v.created_by_id else "System", "at": v.created_at}
            for v in PlatformRules.objects.select_related("created_by")[:10]]})

    @extend_schema(tags=["configuration"], request=Input)
    def put(self, request):
        from apps.audit import services as audit
        from apps.commissions import calculators as calc
        from apps.commissions.models import PlatformRules
        from apps.commissions.services import rules

        d = validated(self.Input, request.data)
        try:
            cleaned = calc.validate_parameters(d["parameters"])
        except calc.RulesError as exc:
            raise BusinessRuleViolation(str(exc), code="invalid_rules") from exc
        with transaction.atomic():
            before = rules()
            new = PlatformRules.publish(parameters=cleaned, actor=request.user, reason=d["reason"])
            audit.record(action="config.platform_rules.published", entity_type="PlatformRules", entity_id=new.pk,
                         actor=request.user, before=before, after=cleaned, reason=d["reason"], request=request)
        return ok({"version": new.version})


class RunJobsView(APIView):
    """Run scheduled jobs now (also handy in development, where nothing runs on a timer)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    class Input(serializers.Serializer):
        jobs = serializers.ListField(child=serializers.ChoiceField(choices=list(jobs.JOBS)), required=False)

    @extend_schema(tags=["configuration"], request=Input)
    def post(self, request):
        from apps.audit import services as audit

        d = validated(self.Input, request.data)
        result = jobs.run(d.get("jobs") or None)
        audit.record(action="jobs.run", entity_type="Jobs", entity_id="manual", actor=request.user,
                     after={"jobs": d.get("jobs") or list(jobs.JOBS)}, request=request)
        return ok(result)
