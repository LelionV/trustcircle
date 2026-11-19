from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from apps.common.uploads import PrivateDocumentField

from .models import KycSubmission


class KycFilesMixin(serializers.Serializer):
    files = serializers.SerializerMethodField()

    def get_files(self, obj) -> dict:
        result = {}
        for field in KycSubmission.FILE_FIELDS:
            if getattr(obj, field):
                result[field] = reverse("v1:kyc-file", kwargs={"pk": obj.pk, "field": field})
        return result


class KycSubmissionSerializer(KycFilesMixin, serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    document_type_label = serializers.CharField(source="get_document_type_display", read_only=True)

    class Meta:
        model = KycSubmission
        fields = (
            "id", "document_type", "document_type_label", "document_number", "legal_first_name",
            "legal_last_name", "date_of_birth", "nationality", "status", "status_label",
            "submitted_at", "reviewed_at", "rejection_reason", "files",
        )
        read_only_fields = fields


class KycCreateSerializer(serializers.ModelSerializer):
    id_front = PrivateDocumentField()
    id_back = PrivateDocumentField(required=False)
    selfie = PrivateDocumentField()
    proof_of_income = PrivateDocumentField(required=False)

    class Meta:
        model = KycSubmission
        fields = (
            "document_type", "document_number", "legal_first_name", "legal_last_name",
            "date_of_birth", "nationality", "id_front", "id_back", "selfie", "proof_of_income",
        )

    def validate_document_number(self, value):
        value = value.strip().upper().replace(" ", "")
        if not value.isalnum() or not 5 <= len(value) <= 20:
            raise serializers.ValidationError("Enter the number exactly as it appears on the document.")
        return value

    def validate_date_of_birth(self, value):
        today = timezone.localdate()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise serializers.ValidationError("You must be 18 or older to use P2P Lend.")
        if age > 110:
            raise serializers.ValidationError("Check the date of birth.")
        return value

    def validate(self, attrs):
        if attrs.get("document_type") == "NATIONAL_ID" and not attrs.get("id_back"):
            raise serializers.ValidationError({"id_back": ["Upload the back of your national ID."]})
        return attrs


class AdminKycSerializer(KycSubmissionSerializer):
    user = serializers.SerializerMethodField()
    reviewed_by_email = serializers.EmailField(source="reviewed_by.email", read_only=True, default=None)
    review_note = serializers.CharField(read_only=True)
    duplicate_document_users = serializers.SerializerMethodField()

    class Meta(KycSubmissionSerializer.Meta):
        fields = KycSubmissionSerializer.Meta.fields + (
            "user", "reviewed_by_email", "review_note", "duplicate_document_users",
        )
        read_only_fields = fields

    def get_user(self, obj) -> dict:
        u = obj.user
        profile = None
        from apps.accounts.profiles import get_profile_data

        profile = get_profile_data(u)
        return {
            "id": str(u.pk), "email": u.email, "full_name": u.full_name, "role": u.role,
            "role_label": u.get_role_display(), "phone_number": u.phone_number,
            "is_email_verified": u.is_email_verified, "is_phone_verified": u.is_phone_verified,
            "date_joined": u.date_joined, "profile": profile,
        }

    def get_duplicate_document_users(self, obj) -> list:
        """Other accounts that submitted the same document number (possible duplicate identity)."""
        return list(
            KycSubmission.objects.filter(document_type=obj.document_type, document_number=obj.document_number)
            .exclude(user_id=obj.user_id)
            .values_list("user__email", flat=True)
            .distinct()
        )


class KycApproveSerializer(serializers.Serializer):
    income_verified = serializers.BooleanField(default=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class KycRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=1000)
