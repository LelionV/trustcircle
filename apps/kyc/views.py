import mimetypes

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import has_permission
from apps.common.permissions import HasPlatformPermission
from apps.common.uploads import sniff

from . import services
from .models import KycStatus, KycSubmission, kyc_status_for
from .serializers import (
    AdminKycSerializer,
    KycApproveSerializer,
    KycCreateSerializer,
    KycRejectSerializer,
    KycSubmissionSerializer,
)


class MyKycView(APIView):
    """Your identity verification: status, latest submission, and new submissions."""

    permission_classes = [HasPlatformPermission]
    required_permission = "kyc.submit"
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(tags=["kyc"])
    def get(self, request):
        latest = request.user.kyc_submissions.order_by("-submitted_at").first()
        return Response({
            "status": kyc_status_for(request.user),
            "submission": KycSubmissionSerializer(latest).data if latest else None,
        })

    @extend_schema(request=KycCreateSerializer, responses=KycSubmissionSerializer, tags=["kyc"])
    def post(self, request):
        serializer = KycCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = services.submit(request.user, serializer.validated_data, request=request)
        return Response(KycSubmissionSerializer(submission).data, status=201)


class KycFileView(APIView):
    """Stream a KYC document to its owner or to an administrator who can see KYC."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["kyc"], responses={(200, "application/octet-stream"): bytes})
    def get(self, request, pk, field):
        if field not in KycSubmission.FILE_FIELDS:
            raise Http404
        submission = get_object_or_404(KycSubmission, pk=pk)
        if submission.user_id != request.user.pk and not has_permission(request.user, "admin.kyc.view"):
            raise Http404  # don't reveal that the document exists
        file = getattr(submission, field)
        if not file:
            raise Http404
        handle = file.open("rb")
        content_type, _ = sniff(handle)
        content_type = content_type or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        response = FileResponse(handle, content_type=content_type)
        response["Content-Disposition"] = f'inline; filename="{field}{file.name[file.name.rfind("."):]}"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


@extend_schema(tags=["kyc"], parameters=[OpenApiParameter("status", str, enum=["PENDING", "APPROVED", "REJECTED"])])
class AdminKycListView(generics.ListAPIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.kyc.view"
    serializer_class = AdminKycSerializer
    filter_backends: list = []

    def get_queryset(self):
        qs = KycSubmission.objects.select_related("user", "reviewed_by")
        status_ = self.request.query_params.get("status", KycStatus.PENDING)
        if status_ in (KycStatus.PENDING, KycStatus.APPROVED, KycStatus.REJECTED):
            qs = qs.filter(status=status_)
        # Oldest first for the review queue; newest first otherwise.
        return qs.order_by("submitted_at" if status_ == KycStatus.PENDING else "-submitted_at")


@extend_schema(tags=["kyc"])
class AdminKycDetailView(generics.RetrieveAPIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.kyc.view"
    serializer_class = AdminKycSerializer
    queryset = KycSubmission.objects.select_related("user", "reviewed_by")


class AdminKycApproveView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.kyc.approve"

    @extend_schema(request=KycApproveSerializer, responses=AdminKycSerializer, tags=["kyc"])
    def post(self, request, pk):
        get_object_or_404(KycSubmission, pk=pk)
        payload = KycApproveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        submission = services.approve(actor=request.user, submission_id=pk, request=request, **payload.validated_data)
        return Response(AdminKycSerializer(submission).data)


class AdminKycRejectView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.kyc.approve"

    @extend_schema(request=KycRejectSerializer, responses=AdminKycSerializer, tags=["kyc"])
    def post(self, request, pk):
        get_object_or_404(KycSubmission, pk=pk)
        payload = KycRejectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        submission = services.reject(actor=request.user, submission_id=pk, reason=payload.validated_data["reason"],
                                     request=request)
        return Response(AdminKycSerializer(submission).data)
