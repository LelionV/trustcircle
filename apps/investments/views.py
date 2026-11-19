from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.common.api import AmountField, IdempotentInput, csv_response, ok, paginated, validated
from apps.common.permissions import HasPlatformPermission

from . import offers, services
from .models import Investment, LoanOffer


def investment_row(i):
    loan = i.loan
    return {
        "id": i.pk, "loan_id": loan.pk, "loan": loan.reference, "loan_status": loan.status,
        "loan_status_label": loan.get_status_display(), "funding_mode": loan.funding_mode,
        "amount": i.amount, "rate": i.rate, "rate_basis": loan.rate_basis, "status": i.status,
        "status_label": i.get_status_display(), "share_percent": i.share_percent,
        "principal_repaid": i.principal_repaid, "interest_earned": i.interest_earned,
        "extension_interest_earned": i.extension_interest_earned, "recovered": i.recovered,
        "outstanding": i.outstanding, "total_earned": i.total_earned, "created_at": i.created_at,
        "risk_class": loan.risk_class_snapshot, "trust_score": loan.trust_score_snapshot,
        "pending_extension": _pending_extension(i),
    }


def _pending_extension(i):
    ext = i.loan.extension_requests.filter(status="AWAITING_CONSENT").first()
    if not ext or i.status != "ACTIVE":
        return None
    vote = ext.votes.filter(investor=i.investor).first()
    return {"id": ext.pk, "days": ext.days, "reason": ext.reason, "extension_interest": ext.extension_interest,
            "deadline": ext.consent_deadline, "mode": ext.rules_snapshot.get("investor_consent"),
            "my_vote": None if vote is None else vote.agrees}


def offer_row(o):
    return {"id": o.pk, "loan_id": o.loan_id, "loan": o.loan.reference, "loan_status": o.loan.status,
            "amount": o.amount, "rate": o.rate, "message": o.message, "status": o.status,
            "status_label": o.get_status_display(), "created_at": o.created_at, "decided_at": o.decided_at}


class InvestView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "investments.make"

    class Input(IdempotentInput):
        amount = AmountField()

    @extend_schema(tags=["investments"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        inv = services.invest(request.user, pk, d["amount"], idempotency_key=d["idempotency_key"], request=request)
        return ok(investment_row(inv), status=201)


class OfferView(APIView):
    """Make an offer (amount and your own rate) on an open-offers loan."""

    permission_classes = [HasPlatformPermission]
    required_permission = "investments.make"

    class Input(serializers.Serializer):
        amount = AmountField()
        rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0)
        message = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    @extend_schema(tags=["offers"], request=Input)
    def post(self, request, pk):
        d = validated(self.Input, request.data)
        o = offers.make_offer(request.user, pk, amount=d["amount"], rate=d["rate"], message=d["message"],
                              request=request)
        return ok(offer_row(o), status=201)


class MyOfferView(APIView):
    """PATCH to change the rate of your open offer; DELETE to withdraw it (money returned)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "investments.make"

    class Input(serializers.Serializer):
        rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0)
        message = serializers.CharField(max_length=500, required=False, allow_blank=True)

    @extend_schema(tags=["offers"], request=Input)
    def patch(self, request, offer_id):
        d = validated(self.Input, request.data)
        return ok(offer_row(offers.change_offer(offer_id, request.user, rate=d["rate"], message=d.get("message"))))

    @extend_schema(tags=["offers"])
    def delete(self, request, offer_id):
        return ok(offer_row(offers.withdraw_offer(offer_id, request.user)))


class MyOffersView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "investments.view_own"

    @extend_schema(tags=["offers"])
    def get(self, request):
        qs = LoanOffer.objects.filter(investor=request.user).select_related("loan")
        return paginated(self, request, qs, offer_row)


class PortfolioView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "investments.view_own"

    @extend_schema(tags=["investments"])
    def get(self, request):
        return ok(services.portfolio(request.user))


class MyInvestmentsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "investments.view_own"

    @extend_schema(tags=["investments"])
    def get(self, request):
        qs = Investment.objects.filter(investor=request.user).select_related("loan")
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        return paginated(self, request, qs, investment_row)


class InvestmentWithdrawView(APIView):
    """Take back a commitment while the loan is still filling up."""

    permission_classes = [HasPlatformPermission]
    required_permission = "investments.make"

    @extend_schema(tags=["investments"], request=None)
    def post(self, request, pk):
        return ok(investment_row(services.withdraw_commitment(pk, request.user, request=request)))


class InvestmentDistributionsView(APIView):
    """Every payment received from one investment."""

    permission_classes = [HasPlatformPermission]
    required_permission = "investments.view_own"

    @extend_schema(tags=["investments"])
    def get(self, request, pk):
        inv = get_object_or_404(Investment, pk=pk, investor=request.user)
        return ok([{"at": d.created_at, "principal": d.principal, "interest": d.interest,
                    "extension_interest": d.extension_interest, "total": d.total, "recovery": d.is_recovery}
                   for d in inv.distributions.order_by("-created_at")])


class ExtensionVoteView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "extensions.vote"

    class Input(serializers.Serializer):
        agrees = serializers.BooleanField()
        comment = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    @extend_schema(tags=["extensions"], request=Input)
    def post(self, request, ext_id):
        from apps.repayments.services import vote

        d = validated(self.Input, request.data)
        ext = vote(ext_id, request.user, d["agrees"], d["comment"])
        return ok({"id": ext.pk, "status": ext.status, "status_label": ext.get_status_display()})


class InvestorStatementView(APIView):
    """CSV of every distribution received (for tax and records)."""

    permission_classes = [HasPlatformPermission]
    required_permission = "statements.view_own"

    @extend_schema(tags=["investments"])
    def get(self, request):
        import csv
        import io

        from apps.repayments.models import DistributionLine

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "loan", "role", "principal", "interest", "extension_interest", "total", "recovery"])
        for d in DistributionLine.objects.filter(recipient=request.user).select_related("loan").order_by("created_at"):
            w.writerow([d.created_at.date(), d.loan.reference, d.role, d.principal, d.interest, d.extension_interest,
                        d.total, "yes" if d.is_recovery else ""])
        return csv_response(buf.getvalue(), "returns-statement.csv")
