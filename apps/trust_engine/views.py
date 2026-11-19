from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPlatformPermission

from .models import TrustEvent, TrustScore


def trust_payload(user, history_limit=60):
    """Everything the Trust score page shows. Shared with the admin user view."""
    from apps.kyc.models import KycStatus, kyc_status_for
    from apps.loans import calculators as calc
    from apps.loans.pricing import active_bracket_set, rows
    from apps.trust_engine import calculators as trust_calc

    score = TrustScore.objects.filter(user=user).first()
    events = list(TrustEvent.objects.filter(user=user).order_by("-created_at")[:history_limit])
    bracket_set = active_bracket_set()
    bracket_rows = rows(bracket_set)
    value = score.score if score else None
    bracket = calc.find_bracket(bracket_rows, value) if value is not None else None
    better = calc.next_better_bracket(bracket_rows, value) if value is not None else None
    kyc = kyc_status_for(user)
    from .services import active_config

    params = active_config().parameters
    return {
        "rules": {
            "punctuality_points": params["punctuality_points"],
            "reward_cap_per_loan": params["reward_cap_per_loan"],
            "min_installment_amount": params["min_installment_amount"],
            "default_penalty": params["default_penalty"],
            "early_completion_bonus": params.get("early_completion_bonus",
                                                 trust_calc.DEFAULT_PARAMETERS["early_completion_bonus"]),
        },
        "rate_basis": bracket_set.basis,
        "is_scored": value is not None,
        "not_scored_reason": None if value is not None else (
            "Your identity documents are being reviewed." if kyc == KycStatus.PENDING
            else "Your score is created once your identity is verified."),
        "score": value,
        "previous_score": score.previous_score if score else None,
        "change": (value - score.previous_score) if score and value is not None and score.previous_score is not None
        else None,
        "confidence": score.confidence if score else "NEW",
        "confidence_label": score.get_confidence_display() if score else "New borrower",
        "bracket": None if bracket is None else {
            "label": bracket["label"],
            "annual_rate": None if bracket["annual_rate"] is None else str(bracket["annual_rate"]),
        },
        "next_bracket": None if better is None else {
            "label": better["label"], "min_score": better["min_score"],
            "annual_rate": str(better["annual_rate"]), "points_needed": better["points_needed"],
        },
        "counts": {
            "installments": score.installments_counted if score else 0,
            "early": score.early_payments if score else 0,
            "on_time": score.on_time_payments if score else 0,
            "late": score.late_payments if score else 0,
            "completed_loans": score.completed_loans if score else 0,
            "defaults": score.defaults if score else 0,
        },
        "breakdown": score.breakdown if score else {},
        "last_assessed_at": score.last_assessed_at if score else None,
        "history": [
            {"at": e.created_at, "type": e.event_type, "type_label": e.get_event_type_display(),
             "points": e.points, "score_before": e.score_before, "score_after": e.score_after,
             "change": e.change, "reason": e.reason}
            for e in events
        ],
    }


class MyTrustView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "trust.view_own"

    @extend_schema(tags=["trust"])
    def get(self, request):
        return Response(trust_payload(request.user))
