from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit

from apps.common.exceptions import BusinessRuleViolation

from .profiles import get_profile_data, update_profile
from .serializers import ProfileUpdateSerializer, UserSerializer


class MeView(APIView):
    """The currently authenticated user, including their computed permissions."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserSerializer, tags=["accounts"])
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=ProfileUpdateSerializer, responses=UserSerializer, tags=["accounts"])
    def patch(self, request):
        user = request.user
        serializer = ProfileUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = {f: getattr(user, f) for f in serializer.validated_data}
        with transaction.atomic():
            serializer.save()
            audit.record(
                action="user.profile.updated",
                entity_type="User",
                entity_id=user.pk,
                actor=user,
                before=before,
                after=dict(serializer.validated_data),
                request=request,
            )
        return Response(UserSerializer(user).data)


class ProfileDetailsView(APIView):
    """
    Your role-specific details: employment and income for borrowers and
    guarantors; occupation and source of funds for investors.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["accounts"])
    def get(self, request):
        return Response({"role": request.user.role, "profile": get_profile_data(request.user)})

    @extend_schema(tags=["accounts"])
    def put(self, request):
        if get_profile_data(request.user) is None:
            raise BusinessRuleViolation("Administrator accounts don't have a customer profile.", code="no_profile")
        update_profile(request.user, request.data, request=request)
        return Response({"role": request.user.role, "profile": get_profile_data(request.user)})
