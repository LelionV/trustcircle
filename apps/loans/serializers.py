from decimal import Decimal

from django.urls import reverse
from rest_framework import serializers

from apps.borrowers.models import EmploymentStatus
from apps.common.uploads import PrivateDocumentField

from . import calculators as calc
from .models import Frequency, Loan, LoanDocument, LoanProduct, LoanPurpose, LoanStatus

MONEY = {"max_digits": 14, "decimal_places": 2}


def schedule_rows(installments):
    return [
        {
            "sequence": i["sequence"], "due_date": i["due_date"], "principal": str(i["principal"]),
            "interest": str(i["interest"]), "fees": str(i["fees"]), "total": str(i["total"]),
            "balance_after": str(i["balance_after"]),
        }
        for i in installments
    ]


def schedule_payload(schedule):
    if schedule is None:
        return None
    return {
        "installment_count": schedule["installment_count"],
        "method": schedule["method"],
        "basis": schedule["basis"],
        "frequency": schedule["frequency"],
        "first_installment": str(schedule["first_installment"]),
        "largest_installment": str(schedule["largest_installment"]),
        "monthly_equivalent": str(schedule["monthly_equivalent"]),
        "total_interest": str(schedule["total_interest"]),
        "total_repayable": str(schedule["total_repayable"]),
        "first_due_date": schedule["first_due_date"],
        "final_due_date": schedule["final_due_date"],
        "installments": schedule_rows(schedule["installments"]),
    }


class LoanProductSerializer(serializers.ModelSerializer):
    interest_method_label = serializers.CharField(source="get_interest_method_display", read_only=True)
    rate_basis_label = serializers.CharField(source="get_rate_basis_display", read_only=True)
    frequencies = serializers.ListField(child=serializers.ChoiceField(choices=Frequency.choices), allow_empty=False)

    class Meta:
        model = LoanProduct
        fields = (
            "id", "name", "description", "min_amount", "max_amount", "min_term_months", "max_term_months",
            "frequencies", "interest_method", "interest_method_label", "rate_basis", "rate_basis_label",
            "requires_guarantor", "funding_period_days", "max_installment_share", "max_open_loans", "is_active",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        lo = attrs.get("min_amount", getattr(self.instance, "min_amount", None))
        hi = attrs.get("max_amount", getattr(self.instance, "max_amount", None))
        if lo is not None and hi is not None and hi < lo:
            raise serializers.ValidationError({"max_amount": ["Must be at least the minimum amount."]})
        tlo = attrs.get("min_term_months", getattr(self.instance, "min_term_months", 1))
        thi = attrs.get("max_term_months", getattr(self.instance, "max_term_months", 1))
        if thi < tlo:
            raise serializers.ValidationError({"max_term_months": ["Must be at least the minimum period."]})
        share = attrs.get("max_installment_share")
        if share is not None and not (Decimal("1") <= share <= Decimal("100")):
            raise serializers.ValidationError({"max_installment_share": ["Enter a percentage between 1 and 100."]})
        return attrs


class LoanTermsSerializer(serializers.Serializer):
    """What a borrower asks for; used for quotes, drafts and updates."""

    product = serializers.PrimaryKeyRelatedField(queryset=LoanProduct.objects.filter(is_active=True))
    amount = serializers.DecimalField(**MONEY, min_value=Decimal("1"))
    term_months = serializers.IntegerField(min_value=1, max_value=120)
    repayment_frequency = serializers.ChoiceField(choices=Frequency.choices)
    purpose = serializers.ChoiceField(choices=LoanPurpose.choices, required=False)
    purpose_details = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    employment_status = serializers.ChoiceField(choices=EmploymentStatus.choices, required=False, allow_blank=True)
    monthly_income = serializers.DecimalField(**MONEY, min_value=Decimal("0"), required=False, allow_null=True)
    monthly_obligations = serializers.DecimalField(**MONEY, min_value=Decimal("0"), required=False)
    guarantor_email = serializers.EmailField(required=False, allow_blank=True)


class LoanDraftSerializer(LoanTermsSerializer):
    purpose = serializers.ChoiceField(choices=LoanPurpose.choices)
    monthly_income = serializers.DecimalField(**MONEY, min_value=Decimal("0"))


class LoanDocumentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = LoanDocument
        fields = ("id", "description", "uploaded_at", "url")

    def get_url(self, obj) -> str:
        return reverse("v1:loan-document", kwargs={"pk": obj.loan_id, "doc_id": obj.pk})


class LoanDocumentUploadSerializer(serializers.Serializer):
    file = PrivateDocumentField()
    description = serializers.CharField(max_length=120)


class LoanSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    purpose_label = serializers.CharField(source="get_purpose_display", read_only=True)
    frequency_label = serializers.CharField(source="get_repayment_frequency_display", read_only=True)
    interest_method_label = serializers.CharField(source="get_interest_method_display", read_only=True)
    product = LoanProductSerializer(read_only=True)
    guarantor = serializers.SerializerMethodField()
    schedule = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    documents = LoanDocumentSerializer(many=True, read_only=True)
    terms_locked = serializers.BooleanField(read_only=True)
    rate_basis_label = serializers.CharField(source="get_rate_basis_display", read_only=True)
    funding_mode_label = serializers.CharField(source="get_funding_mode_display", read_only=True)
    agreement = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()
    offers = serializers.SerializerMethodField()
    extensions = serializers.SerializerMethodField()
    funding = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = (
            "id", "reference", "status", "status_label", "product", "amount", "term_months",
            "repayment_frequency", "frequency_label", "purpose", "purpose_label", "purpose_details",
            "employment_status", "monthly_income", "monthly_obligations", "guarantor",
            "trust_score_snapshot", "trust_confidence_snapshot", "risk_score_snapshot", "risk_class_snapshot",
            "bracket_label", "annual_rate", "interest_method", "interest_method_label", "rate_basis",
            "requires_manual_pricing", "installment_count", "installment_amount", "total_interest",
            "total_repayable", "terms_locked", "terms_locked_at", "submitted_at", "decided_at",
            "decision_reason", "published_at", "funding_expires_at", "funded_amount", "created_at",
            "schedule", "history", "documents", "rate_basis_label", "funding_mode", "funding_mode_label",
            "fully_funded_at", "disbursed_at", "overdue_since", "completed_at", "defaulted_at", "extension_count",
            "agreement", "outstanding", "offers", "extensions", "funding",
        )
        read_only_fields = fields

    def get_guarantor(self, obj) -> dict | None:
        g = obj.guarantees.select_related("guarantor").order_by("-created_at").first()
        if g is not None:
            return {"name": g.guarantor.full_name, "email": g.guarantor.email, "status": g.status,
                    "status_label": g.get_status_display(), "note": g.response_note,
                    "locked_interest": str(g.locked_amount)}
        p = obj.proposed_guarantor
        if p is None:
            return None
        return {"name": p.full_name, "email": p.email, "status": "NOMINATED",
                "status_label": "Asked when the loan opens for funding", "note": "", "locked_interest": "0.00"}

    def get_schedule(self, obj) -> list:
        if obj.terms_locked and obj.installments.exists():
            from .models import INSTALLMENT_COMPONENTS

            return [
                {"sequence": i.sequence, "due_date": i.due_date, "original_due_date": i.original_due_date,
                 "principal": str(i.principal), "interest": str(i.interest), "fees": str(i.fees),
                 "late_fee": str(i.late_fee), "extension_fee": str(i.extension_fee),
                 "extension_interest": str(i.extension_interest), "total": str(i.amount_due),
                 "paid": str(i.amount_paid), "outstanding": str(i.outstanding),
                 "balance_after": str(i.balance_after), "status": i.status,
                 "status_label": i.get_status_display(), "paid_at": i.paid_at,
                 "components": {c: {"due": str(getattr(i, c)), "paid": str(getattr(i, f"{c}_paid"))}
                                for c in INSTALLMENT_COMPONENTS}}
                for i in obj.installments.all()
            ]
        if obj.annual_rate is None:
            return []
        from django.utils import timezone

        preview = calc.build_schedule(
            principal=obj.amount, annual_rate=obj.annual_rate, method=obj.interest_method or obj.product.interest_method,
            basis=obj.rate_basis or obj.product.rate_basis, frequency=obj.repayment_frequency,
            term_months=obj.term_months, start_date=timezone.localdate(),
        )
        return schedule_rows(preview["installments"])

    def get_agreement(self, obj) -> dict | None:
        a = obj.agreements.order_by("-version").first()
        if a is None:
            return None
        return {"version": a.version, "text": a.text, "accepted_at": a.accepted_at, "created_at": a.created_at}

    def get_outstanding(self, obj) -> dict | None:
        if obj.status not in ("ACTIVE", "OVERDUE", "DEFAULTED"):
            return None
        from .models import INSTALLMENT_COMPONENTS, PAID_STATUSES

        unpaid = [i for i in obj.installments.all() if i.status not in PAID_STATUSES]
        result = {c: sum((i.due(c) for i in unpaid), Decimal("0.00")) for c in INSTALLMENT_COMPONENTS}
        nxt = unpaid[0] if unpaid else None
        return {**{k: str(v) for k, v in result.items()}, "total": str(sum(result.values(), Decimal("0.00"))),
                "next_due_date": nxt.due_date if nxt else None,
                "next_due_amount": str(nxt.outstanding) if nxt else "0.00"}

    def get_offers(self, obj) -> list:
        if obj.funding_mode != "OFFERS":
            return []
        from apps.chat.services import display_name

        return [{"id": o.pk, "investor": display_name(o.investor), "investor_id": o.investor_id,
                 "amount": str(o.amount), "rate": str(o.rate), "message": o.message, "status": o.status,
                 "status_label": o.get_status_display(), "created_at": o.created_at}
                for o in obj.offers.select_related("investor").order_by("status", "rate", "-amount")]

    def get_extensions(self, obj) -> list:
        return [{"id": e.pk, "days": e.days, "reason": e.reason, "status": e.status,
                 "status_label": e.get_status_display(), "extension_interest": str(e.extension_interest),
                 "extension_fee": str(e.extension_fee), "consent_deadline": e.consent_deadline,
                 "decision_reason": e.decision_reason, "created_at": e.created_at}
                for e in obj.extension_requests.all()]

    def get_funding(self, obj) -> dict:
        funded = obj.funded_amount or Decimal("0")
        return {"funded": str(funded), "remaining": str(obj.amount - funded),
                "percent": int(funded * 100 / obj.amount) if obj.amount else 0,
                "investors": obj.investments.exclude(status="REFUNDED").values("investor").distinct().count()}

    def get_history(self, obj) -> list:
        return [
            {"from": h.from_status, "to": h.to_status, "to_label": LoanStatus(h.to_status).label,
             "reason": h.reason, "at": h.created_at}
            for h in obj.status_history.all()
        ]


class AdminLoanSerializer(LoanSerializer):
    borrower = serializers.SerializerMethodField()
    reviewed_by_email = serializers.EmailField(source="reviewed_by.email", read_only=True, default=None)

    class Meta(LoanSerializer.Meta):
        fields = LoanSerializer.Meta.fields + ("borrower", "reviewed_by_email")
        read_only_fields = fields

    def get_borrower(self, obj) -> dict:
        from apps.administration.serializers import customer_summary

        return customer_summary(obj.borrower)


class AdminLoanListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    borrower_name = serializers.CharField(source="borrower.full_name", read_only=True)
    borrower_email = serializers.EmailField(source="borrower.email", read_only=True)

    class Meta:
        model = Loan
        fields = ("id", "reference", "status", "status_label", "amount", "term_months", "annual_rate",
                  "trust_score_snapshot", "risk_class_snapshot", "requires_manual_pricing", "submitted_at", "funding_mode",
                  "funded_amount", "disbursed_at",
                  "created_at", "borrower_name", "borrower_email")
        read_only_fields = fields


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=1000)


class ApproveSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=1000)
    annual_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"),
                                           max_value=Decimal("100"), required=False, allow_null=True)


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class MarketplaceLoanSerializer(serializers.ModelSerializer):
    """What investors see: enough to judge the loan, without identifying the borrower."""

    purpose_label = serializers.CharField(source="get_purpose_display", read_only=True)
    frequency_label = serializers.CharField(source="get_repayment_frequency_display", read_only=True)
    interest_method_label = serializers.CharField(source="get_interest_method_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    borrower = serializers.SerializerMethodField()
    guarantor = serializers.SerializerMethodField()
    funding = serializers.SerializerMethodField()
    rate_basis_label = serializers.CharField(source="get_rate_basis_display", read_only=True)
    offers = serializers.SerializerMethodField()
    mine = serializers.SerializerMethodField()
    current_trust_score = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = (
            "id", "reference", "status", "status_label", "amount", "term_months", "repayment_frequency",
            "frequency_label", "purpose", "purpose_label", "purpose_details", "annual_rate", "interest_method",
            "interest_method_label", "installment_count", "installment_amount", "total_interest",
            "trust_score_snapshot", "trust_confidence_snapshot", "risk_score_snapshot", "risk_class_snapshot",
            "bracket_label", "published_at", "funding_expires_at", "borrower", "guarantor", "funding",
            "funding_mode", "rate_basis", "rate_basis_label", "offers", "mine", "current_trust_score",
        )
        read_only_fields = fields

    def get_borrower(self, obj) -> dict:
        from apps.accounts.profiles import get_profile
        from apps.trust_engine.models import TrustScore

        u = obj.borrower
        profile = get_profile(u)
        trust = TrustScore.objects.filter(user=u).first()
        initial = (u.last_name[:1] + ".") if u.last_name else ""
        return {
            "display_name": f"{u.first_name} {initial}".strip() or "Borrower",
            "county": getattr(profile, "county", ""),
            "employment_status": getattr(profile, "get_employment_status_display", lambda: "")(),
            "income_verified": getattr(profile, "income_verified", False),
            "is_new_borrower": (trust.confidence if trust else "NEW") == "NEW",
            "completed_loans": trust.completed_loans if trust else 0,
            "on_time_or_early": (trust.early_payments + trust.on_time_payments) if trust else 0,
            "late_payments": trust.late_payments if trust else 0,
            "member_since": u.date_joined.date(),
        }

    def get_guarantor(self, obj) -> dict:
        if obj.funding_mode == "OFFERS":
            return {"named": False, "status": "No guarantor: open offers. Investors set their own rate."}
        g = obj.guarantees.order_by("-created_at").first()
        if g and g.status == "ACCEPTED":
            return {"named": True, "status": "Guarantor has accepted and locked the interest"}
        return {"named": True, "status": "Guarantor named; acceptance is confirmed before pay-out"}

    def get_funding(self, obj) -> dict:
        funded = obj.funded_amount or Decimal("0")
        return {
            "funded": str(funded),
            "remaining": str(obj.amount - funded),
            "percent": int(funded * 100 / obj.amount) if obj.amount else 0,
            "investors": obj.investments.exclude(status="REFUNDED").values("investor").distinct().count(),
        }

    def get_offers(self, obj) -> dict | None:
        if obj.funding_mode != "OFFERS":
            return None
        from django.db.models import Count, Max, Min

        stats = obj.offers.filter(status="OPEN").aggregate(n=Count("pk"), low=Min("rate"), high=Max("rate"))
        return {"open": stats["n"], "lowest_rate": stats["low"] and str(stats["low"]),
                "highest_rate": stats["high"] and str(stats["high"])}

    def get_mine(self, obj) -> dict:
        user = self.context.get("request") and self.context["request"].user
        if not user or not user.is_authenticated:
            return {}
        offer = obj.offers.filter(investor=user, status="OPEN").first()
        invested = sum((i.amount for i in obj.investments.filter(investor=user).exclude(status="REFUNDED")),
                       Decimal("0.00"))
        return {"invested": str(invested),
                "offer": {"id": offer.pk, "amount": str(offer.amount), "rate": str(offer.rate),
                          "message": offer.message} if offer else None,
                "is_guarantor": obj.guarantees.filter(guarantor=user, status__in=["REQUESTED", "ACCEPTED"]).exists()}

    def get_current_trust_score(self, obj) -> int | None:
        from apps.trust_engine.models import TrustScore

        t = TrustScore.objects.filter(user=obj.borrower).first()
        return t.score if t else None
