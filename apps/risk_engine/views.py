from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPlatformPermission

from .calculators import CLASS_LABELS
from .models import RiskProfile


def risk_payload(user, include_override_details=False):
    profile = RiskProfile.objects.filter(user=user).first()
    if profile is None:
        return {"is_assessed": False}
    data = {
        "is_assessed": True,
        "score": profile.score,
        "classification": profile.effective_classification,
        "classification_label": CLASS_LABELS[profile.effective_classification],
        "calculated_classification": profile.classification,
        "is_overridden": bool(profile.override_classification),
        "factors": profile.factors,
        "assessed_at": profile.assessed_at,
    }
    if include_override_details and profile.override_classification:
        data["override"] = {
            "reason": profile.override_reason,
            "by": profile.override_by.email if profile.override_by else None,
            "at": profile.override_at,
        }
    return data


class MyRiskView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "risk.view_own"

    @extend_schema(tags=["risk"])
    def get(self, request):
        return Response(risk_payload(request.user))
