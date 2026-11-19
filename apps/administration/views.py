from datetime import timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AdminLevel, Role, User
from apps.accounts.permissions import has_permission
from apps.audit.models import AuditLog
from apps.common.permissions import HasPlatformPermission

from . import services
from .serializers import (
    AdminUserSerializer,
    AuditLogSerializer,
    BracketChangeSerializer,
    ConfigChangeSerializer,
    FreezeSerializer,
    RiskOverrideSerializer,
    RoleChangeSerializer,
    TrustAdjustSerializer,
    customer_summary,
)


class OverviewView(APIView):
    """Headline numbers for the admin dashboard (users only until later phases)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.dashboard.view"

    @extend_schema(
        tags=["administration"],
        responses=inline_serializer(
            name="AdminOverview",
            fields={
                "users_total": serializers.IntegerField(),
                "users_by_role": serializers.DictField(child=serializers.IntegerField()),
                "admins_by_level": serializers.DictField(child=serializers.IntegerField()),
                "frozen_accounts": serializers.IntegerField(),
                "email_unverified": serializers.IntegerField(),
                "phone_unverified": serializers.IntegerField(),
                "joined_last_7_days": serializers.IntegerField(),
                "recent_audit": AuditLogSerializer(many=True),
            },
        ),
    )
    def get(self, request):
        week_ago = timezone.now() - timedelta(days=7)
        totals = User.objects.filter(is_active=True).aggregate(
            users_total=Count("pk"),
            frozen_accounts=Count("pk", filter=Q(is_frozen=True)),
            email_unverified=Count("pk", filter=Q(is_email_verified=False)),
            phone_unverified=Count("pk", filter=Q(is_phone_verified=False)),
            joined_last_7_days=Count("pk", filter=Q(date_joined__gte=week_ago)),
        )
        by_role = dict(
            User.objects.filter(is_active=True).order_by().values_list("role").annotate(n=Count("pk"))
        )
        by_level = dict(
            User.objects.filter(is_active=True, role=Role.ADMIN)
            .order_by()
            .values_list("admin_level")
            .annotate(n=Count("pk"))
        )
        from apps.kyc.models import KycStatus, KycSubmission
        from apps.loans.models import Loan, LoanStatus

        loans_by_status = dict(Loan.objects.order_by().values_list("status").annotate(n=Count("pk")))
        recent = []
        if has_permission(request.user, "admin.audit.view"):
            recent = AuditLogSerializer(
                AuditLog.objects.select_related("actor")[:6], many=True
            ).data
        return Response(
            {
                **totals,
                "users_by_role": {r.value: by_role.get(r.value, 0) for r in Role},
                "admins_by_level": {
                    lvl.value: by_level.get(lvl.value, 0) for lvl in AdminLevel if lvl != AdminLevel.NONE
                },
                "recent_audit": recent,
                "kyc_pending": KycSubmission.objects.filter(status=KycStatus.PENDING).count(),
                "loans_by_status": {st.value: loans_by_status.get(st.value, 0) for st in LoanStatus},
            }
        )


@extend_schema(
    tags=["administration"],
    parameters=[
        OpenApiParameter("role", str, enum=[r.value for r in Role]),
        OpenApiParameter("status", str, enum=["active", "frozen", "inactive"]),
        OpenApiParameter("search", str, description="Email, phone or name"),
    ],
)
class UserListView(generics.ListAPIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.users.view"
    serializer_class = AdminUserSerializer
    filter_backends: list = []  # filtering is explicit below

    def get_queryset(self):
        qs = User.objects.all().order_by("-date_joined")
        params = self.request.query_params
        role = params.get("role")
        if role in Role.values:
            qs = qs.filter(role=role)
        status_ = params.get("status")
        if status_ == "frozen":
            qs = qs.filter(is_frozen=True)
        elif status_ == "active":
            qs = qs.filter(is_active=True, is_frozen=False)
        elif status_ == "inactive":
            qs = qs.filter(is_active=False)
        term = (params.get("search") or "").strip()
        if term:
            qs = qs.filter(
                Q(email__icontains=term)
                | Q(phone_number__icontains=term)
                | Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
            )
        return qs


class UserDetailView(APIView):
    """A user with their profile, KYC status, trust score and risk rating."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.users.view"

    @extend_schema(tags=["administration"])
    def get(self, request, pk):
        return Response(customer_summary(get_object_or_404(User, pk=pk)))


class RoleChangeView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.roles.manage"

    @extend_schema(request=RoleChangeSerializer, tags=["administration"])
    def post(self, request, pk):
        get_object_or_404(User, pk=pk)
        s = RoleChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = services.change_role(actor=request.user, target_id=pk, request=request, **s.validated_data)
        return Response(customer_summary(user))


class TrustAdjustView(APIView):
    """Audited manual adjustment of a borrower's trust score (never a silent edit)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.trust.override"

    @extend_schema(request=TrustAdjustSerializer, tags=["administration"])
    def post(self, request, pk):
        from apps.trust_engine.services import manual_adjust

        user = get_object_or_404(User, pk=pk)
        s = TrustAdjustSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        manual_adjust(actor=request.user, user=user, request=request, **s.validated_data)
        return Response(customer_summary(user))


class RiskOverrideView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.risk.override"

    @extend_schema(request=RiskOverrideSerializer, tags=["administration"])
    def post(self, request, pk):
        from apps.risk_engine.services import override_classification

        user = get_object_or_404(User, pk=pk)
        s = RiskOverrideSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        override_classification(actor=request.user, user=user, request=request, **s.validated_data)
        return Response(customer_summary(user))


class _FreezeBase(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.accounts.freeze"
    frozen: bool

    @extend_schema(request=FreezeSerializer, responses=AdminUserSerializer, tags=["administration"])
    def post(self, request, pk):
        get_object_or_404(User, pk=pk)
        payload = FreezeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user = services.set_account_frozen(
            actor=request.user,
            target_id=pk,
            frozen=self.frozen,
            reason=payload.validated_data["reason"],
            request=request,
        )
        return Response(AdminUserSerializer(user).data)


class FreezeUserView(_FreezeBase):
    """Freeze an account: blocks withdrawals, transfers, new investments and applications."""

    frozen = True


class UnfreezeUserView(_FreezeBase):
    frozen = False


@extend_schema(
    tags=["administration"],
    parameters=[
        OpenApiParameter("action", str, description="Exact action, e.g. user.account.frozen"),
        OpenApiParameter("entity_type", str),
        OpenApiParameter("entity_id", str),
        OpenApiParameter("search", str, description="Action, entity id, actor email or reason"),
    ],
)
class AuditLogListView(generics.ListAPIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.audit.view"
    serializer_class = AuditLogSerializer
    filter_backends: list = []

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor").order_by("-created_at")
        params = self.request.query_params
        for field in ("action", "entity_type", "entity_id"):
            if params.get(field):
                qs = qs.filter(**{field: params[field]})
        term = (params.get("search") or "").strip()
        if term:
            qs = qs.filter(
                Q(action__icontains=term)
                | Q(entity_id__icontains=term)
                | Q(actor__email__icontains=term)
                | Q(reason__icontains=term)
            )
        return qs


# --- Configuration ---------------------------------------------------------------------

def _history(model, limit=10):
    return [
        {"version": c.version, "is_active": c.is_active, "reason": c.reason,
         "by": c.created_by.email if c.created_by else "System", "at": c.created_at}
        for c in model.objects.select_related("created_by")[:limit]
    ]


class ConfigView(APIView):
    """All platform rules on one page: interest brackets, trust scoring, risk thresholds."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(tags=["configuration"])
    def get(self, request):
        from apps.loans.models import InterestBracketSet
        from apps.loans.pricing import active_bracket_set, rows
        from apps.risk_engine import calculators as risk_calc
        from apps.risk_engine.models import RiskConfig
        from apps.risk_engine.services import active_config as risk_config
        from apps.trust_engine import calculators as trust_calc
        from apps.trust_engine.models import TrustConfig
        from apps.trust_engine.services import active_config as trust_config

        brackets = active_bracket_set()
        trust = trust_config()
        risk = risk_config()
        return Response({
            "brackets": {
                "version": brackets.version,
                "rate_basis": brackets.basis,
                "rows": [{**r, "annual_rate": None if r["annual_rate"] is None else str(r["annual_rate"])}
                         for r in rows(brackets)],
                "history": [
                    {"version": b.version, "is_active": b.is_active, "reason": b.reason,
                     "by": b.created_by.email if b.created_by else "System", "at": b.created_at}
                    for b in InterestBracketSet.objects.select_related("created_by")[:10]
                ],
            },
            "trust": {"version": trust.version, "parameters": trust.parameters, "history": _history(TrustConfig),
                      "component_labels": trust_calc.COMPONENT_LABELS},
            "risk": {"version": risk.version, "parameters": risk.parameters, "history": _history(RiskConfig),
                     "factor_labels": risk_calc.FACTOR_LABELS, "class_labels": risk_calc.CLASS_LABELS},
        })


class BracketConfigView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(request=BracketChangeSerializer, tags=["configuration"])
    def put(self, request):
        from apps.loans.pricing import publish_brackets

        s = BracketChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        new_set = publish_brackets(actor=request.user, request=request, **s.validated_data)
        return Response({"version": new_set.version})


class TrustConfigView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(request=ConfigChangeSerializer, tags=["configuration"])
    def put(self, request):
        from django.db import transaction

        from apps.audit import services as audit
        from apps.common.exceptions import BusinessRuleViolation
        from apps.trust_engine import calculators as trust_calc
        from apps.trust_engine.models import TrustConfig
        from apps.trust_engine.services import active_config, recalculate_all

        s = ConfigChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            params = trust_calc.validate_parameters(s.validated_data["parameters"])
        except trust_calc.ParameterError as exc:
            raise BusinessRuleViolation(str(exc), code="invalid_parameters") from exc
        with transaction.atomic():
            previous = active_config()
            config = TrustConfig.publish(parameters=params, actor=request.user, reason=s.validated_data["reason"])
            audit.record(action="config.trust.published", entity_type="TrustConfig", entity_id=config.pk,
                         actor=request.user, before=previous.parameters, after=params,
                         reason=s.validated_data["reason"], request=request)
        updated = recalculate_all(f"Scoring rules changed to version {config.version}", actor=request.user)
        return Response({"version": config.version, "borrowers_rescored": updated})


class RiskConfigView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(request=ConfigChangeSerializer, tags=["configuration"])
    def put(self, request):
        from django.db import transaction

        from apps.audit import services as audit
        from apps.common.exceptions import BusinessRuleViolation
        from apps.risk_engine import calculators as risk_calc
        from apps.risk_engine.models import RiskConfig
        from apps.risk_engine.services import active_config, reassess_all

        s = ConfigChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            params = risk_calc.validate_parameters(s.validated_data["parameters"])
        except risk_calc.ParameterError as exc:
            raise BusinessRuleViolation(str(exc), code="invalid_parameters") from exc
        with transaction.atomic():
            previous = active_config()
            config = RiskConfig.publish(parameters=params, actor=request.user, reason=s.validated_data["reason"])
            audit.record(action="config.risk.published", entity_type="RiskConfig", entity_id=config.pk,
                         actor=request.user, before=previous.parameters, after=params,
                         reason=s.validated_data["reason"], request=request)
        updated = reassess_all(f"Risk rules changed to version {config.version}")
        return Response({"version": config.version, "users_reassessed": updated})
