import mimetypes

from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import has_permission
from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation
from apps.common.permissions import HasPlatformPermission
from apps.common.uploads import sniff

from . import calculators as calc
from . import services
from .models import MARKETPLACE_STATUSES, Loan, LoanDocument, LoanProduct, LoanStatus
from .pricing import active_bracket_set, rows
from .serializers import (
    AdminLoanListSerializer,
    AdminLoanSerializer,
    ApproveSerializer,
    CancelSerializer,
    LoanDocumentSerializer,
    LoanDocumentUploadSerializer,
    LoanDraftSerializer,
    LoanProductSerializer,
    LoanSerializer,
    LoanTermsSerializer,
    MarketplaceLoanSerializer,
    ReasonSerializer,
    schedule_payload,
)


class InterestBracketsView(APIView):
    """Interest brackets currently in force, and where the signed-in borrower sits."""

    permission_classes = [HasPlatformPermission]
    required_permission = "pricing.view"

    @extend_schema(tags=["pricing"])
    def get(self, request):
        from apps.trust_engine.calculators import DEFAULT_PARAMETERS
        from apps.trust_engine.services import active_config

        bracket_set = active_bracket_set()
        bracket_rows = rows(bracket_set)
        payload = {
            "name": f"Version {bracket_set.version}",
            "version": bracket_set.version,
            "source": "configured" if bracket_set.created_by_id else "initial_configuration",
            "rate_basis": bracket_set.basis,
            "new_borrower_score": active_config().parameters.get("initial_score", DEFAULT_PARAMETERS["initial_score"]),
            "brackets": [
                {**r, "annual_rate": None if r["annual_rate"] is None else str(r["annual_rate"]),
                 "manual_review": r["annual_rate"] is None}
                for r in bracket_rows
            ],
            "you": None,
        }
        score = getattr(getattr(request.user, "trust_score", None), "score", None)
        if score is not None:
            current = calc.find_bracket(bracket_rows, score)
            better = calc.next_better_bracket(bracket_rows, score)
            payload["you"] = {
                "score": score,
                "bracket": current["label"] if current else None,
                "annual_rate": None if not current or current["annual_rate"] is None else str(current["annual_rate"]),
                "next": None if not better else {
                    "label": better["label"], "min_score": better["min_score"],
                    "annual_rate": str(better["annual_rate"]), "points_needed": better["points_needed"],
                },
            }
        return Response(payload)


# --- Borrowers ------------------------------------------------------------------------

class ProductListView(generics.ListAPIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "loans.view_own"
    serializer_class = LoanProductSerializer
    pagination_class = None
    filter_backends: list = []

    def get_queryset(self):
        services.default_product()
        return LoanProduct.objects.filter(is_active=True)


class QuoteView(APIView):
    """Price a loan for the signed-in borrower without saving anything."""

    permission_classes = [HasPlatformPermission]
    required_permission = "loans.view_own"

    @extend_schema(request=LoanTermsSerializer, tags=["loans"])
    def post(self, request):
        s = LoanTermsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        guarantor = None
        if d.get("guarantor_email"):
            try:
                guarantor = services._guarantor_from_email(request.user, d["guarantor_email"])
            except BusinessRuleViolation:
                guarantor = None
        result = services.quote(
            request.user, product=d["product"], amount=d["amount"], term_months=d["term_months"],
            frequency=d["repayment_frequency"], monthly_income=d.get("monthly_income"),
            monthly_obligations=d.get("monthly_obligations"), guarantor=guarantor,
        )
        bracket = result["bracket"]
        return Response({
            **result,
            "annual_rate": None if result["annual_rate"] is None else str(result["annual_rate"]),
            "bracket": None if bracket is None else {
                **bracket, "annual_rate": None if bracket["annual_rate"] is None else str(bracket["annual_rate"])},
            "schedule": schedule_payload(result["schedule"]),
        })


class MyLoansView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permissions = {"GET": "loans.view_own", "POST": "loans.apply"}

    @extend_schema(responses=LoanSerializer(many=True), tags=["loans"])
    def get(self, request):
        loans = (Loan.objects.filter(borrower=request.user)
                 .select_related("product", "proposed_guarantor")
                 .prefetch_related("status_history", "documents", "installments"))
        return Response(LoanSerializer(loans, many=True).data)

    @extend_schema(request=LoanDraftSerializer, responses=LoanSerializer, tags=["loans"])
    def post(self, request):
        s = LoanDraftSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        loan = services.create_draft(request.user, dict(s.validated_data), request=request)
        return Response(LoanSerializer(loan).data, status=status.HTTP_201_CREATED)


def _own_loan(request, pk):
    loan = get_object_or_404(Loan.objects.select_related("product"), pk=pk)
    if loan.borrower_id != request.user.pk:
        raise Http404
    return loan


class MyLoanDetailView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permissions = {"GET": "loans.view_own", "PATCH": "loans.apply"}

    @extend_schema(responses=LoanSerializer, tags=["loans"])
    def get(self, request, pk):
        return Response(LoanSerializer(_own_loan(request, pk)).data)

    @extend_schema(request=LoanDraftSerializer, responses=LoanSerializer, tags=["loans"])
    def patch(self, request, pk):
        _own_loan(request, pk)
        s = LoanDraftSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        loan = services.update_draft(pk, request.user, dict(s.validated_data))
        return Response(LoanSerializer(loan).data)


class MyLoanSubmitView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "loans.apply"

    @extend_schema(request=None, responses=LoanSerializer, tags=["loans"])
    def post(self, request, pk):
        _own_loan(request, pk)
        return Response(LoanSerializer(services.submit(pk, request.user, request=request)).data)


class MyLoanCancelView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "loans.view_own"

    @extend_schema(request=CancelSerializer, responses=LoanSerializer, tags=["loans"])
    def post(self, request, pk):
        _own_loan(request, pk)
        s = CancelSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        loan = services.cancel_any(pk, request.user, s.validated_data.get("reason", ""), request=request)
        return Response(LoanSerializer(loan).data)


class LoanDocumentsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "loans.apply"
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=LoanDocumentUploadSerializer, responses=LoanDocumentSerializer, tags=["loans"])
    def post(self, request, pk):
        loan = _own_loan(request, pk)
        if loan.status not in (LoanStatus.DRAFT, LoanStatus.SUBMITTED, LoanStatus.UNDER_REVIEW):
            raise BusinessRuleViolation("Documents can only be added before a decision is made.",
                                        code="documents_closed")
        if loan.documents.count() >= 10:
            raise BusinessRuleViolation("You can attach up to 10 documents.", code="too_many_documents")
        s = LoanDocumentUploadSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        doc = LoanDocument.objects.create(loan=loan, uploaded_by=request.user, **s.validated_data)
        audit.record(action="loan.document_added", entity_type="Loan", entity_id=loan.pk, actor=request.user,
                     after={"document": str(doc.pk), "description": doc.description}, request=request)
        return Response(LoanDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class LoanDocumentFileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["loans"], responses={(200, "application/octet-stream"): bytes})
    def get(self, request, pk, doc_id):
        doc = get_object_or_404(LoanDocument.objects.select_related("loan"), pk=doc_id, loan_id=pk)
        if doc.loan.borrower_id != request.user.pk and not has_permission(request.user, "admin.loans.view"):
            raise Http404
        handle = doc.file.open("rb")
        content_type = sniff(handle)[0] or mimetypes.guess_type(doc.file.name)[0] or "application/octet-stream"
        response = FileResponse(handle, content_type=content_type)
        response["Content-Disposition"] = "inline"
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


# --- Investors ------------------------------------------------------------------------------

class MarketplaceView(generics.ListAPIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "marketplace.view"
    serializer_class = MarketplaceLoanSerializer
    filter_backends: list = []

    def get_queryset(self):
        qs = (Loan.objects.filter(status__in=MARKETPLACE_STATUSES)
              .select_related("borrower", "product").order_by("funding_expires_at"))
        risk = self.request.query_params.get("risk")
        if risk:
            qs = qs.filter(risk_class_snapshot=risk)
        mode = self.request.query_params.get("mode")
        if mode in ("STANDARD", "OFFERS"):
            qs = qs.filter(funding_mode=mode)
        return qs


class MarketplaceDetailView(generics.RetrieveAPIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "marketplace.view"
    serializer_class = MarketplaceLoanSerializer
    queryset = Loan.objects.filter(status__in=MARKETPLACE_STATUSES).select_related("borrower", "product")


# --- Administrators --------------------------------------------------------------------------

@extend_schema(tags=["loans"], parameters=[
    OpenApiParameter("status", str, enum=[s.value for s in LoanStatus]),
    OpenApiParameter("search", str, description="Reference, borrower name or email"),
])
class AdminLoanListView(generics.ListAPIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.loans.view"
    serializer_class = AdminLoanListSerializer
    filter_backends: list = []

    def get_queryset(self):
        qs = Loan.objects.select_related("borrower").exclude(status=LoanStatus.DRAFT)
        st = self.request.query_params.get("status")
        if st in LoanStatus.values:
            qs = qs.filter(status=st)
        term = (self.request.query_params.get("search") or "").strip()
        if term:
            qs = qs.filter(Q(reference__icontains=term) | Q(borrower__email__icontains=term)
                           | Q(borrower__first_name__icontains=term) | Q(borrower__last_name__icontains=term))
        if st in ("SUBMITTED", "UNDER_REVIEW"):
            return qs.order_by("submitted_at")
        return qs.order_by("-created_at")


class AdminLoanDetailView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.loans.view"

    @extend_schema(responses=AdminLoanSerializer, tags=["loans"])
    def get(self, request, pk):
        loan = get_object_or_404(Loan.objects.select_related("product", "borrower", "proposed_guarantor"), pk=pk)
        if loan.status == LoanStatus.DRAFT:
            raise Http404
        return Response(AdminLoanSerializer(loan).data)


class _AdminLoanAction(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.loans.approve"

    def respond(self, loan):
        return Response(AdminLoanSerializer(Loan.objects.get(pk=loan.pk)).data)


class AdminStartReviewView(_AdminLoanAction):
    @extend_schema(request=None, responses=AdminLoanSerializer, tags=["loans"])
    def post(self, request, pk):
        get_object_or_404(Loan, pk=pk)
        return self.respond(services.start_review(pk, request.user, request=request))


class AdminApproveView(_AdminLoanAction):
    @extend_schema(request=ApproveSerializer, responses=AdminLoanSerializer, tags=["loans"])
    def post(self, request, pk):
        get_object_or_404(Loan, pk=pk)
        s = ApproveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self.respond(services.approve(pk, request.user, s.validated_data["reason"],
                                             manual_rate=s.validated_data.get("annual_rate"), request=request))


class AdminRejectView(_AdminLoanAction):
    @extend_schema(request=ReasonSerializer, responses=AdminLoanSerializer, tags=["loans"])
    def post(self, request, pk):
        get_object_or_404(Loan, pk=pk)
        s = ReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self.respond(services.reject(pk, request.user, s.validated_data["reason"], request=request))


class AdminPublishView(_AdminLoanAction):
    @extend_schema(request=None, responses=AdminLoanSerializer, tags=["loans"])
    def post(self, request, pk):
        get_object_or_404(Loan, pk=pk)
        return self.respond(services.publish(pk, request.user, request=request))


class AdminProductsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(responses=LoanProductSerializer(many=True), tags=["configuration"])
    def get(self, request):
        services.default_product()
        return Response(LoanProductSerializer(LoanProduct.objects.all(), many=True).data)

    @extend_schema(request=LoanProductSerializer, responses=LoanProductSerializer, tags=["configuration"])
    def post(self, request):
        s = LoanProductSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        product = services.save_product(actor=request.user, data=dict(s.validated_data), request=request)
        return Response(LoanProductSerializer(product).data, status=status.HTTP_201_CREATED)


class AdminProductDetailView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(request=LoanProductSerializer, responses=LoanProductSerializer, tags=["configuration"])
    def patch(self, request, pk):
        product = get_object_or_404(LoanProduct, pk=pk)
        s = LoanProductSerializer(product, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        product = services.save_product(actor=request.user, data=dict(s.validated_data), product=product,
                                        request=request)
        return Response(LoanProductSerializer(product).data)
