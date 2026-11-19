"""Shared builders for the phase 2–4 tests."""
import struct
import zlib
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import AdminLevel, Role, User
from apps.accounts.profiles import get_profile
from apps.kyc import services as kyc_services
from apps.kyc.models import KycSubmission

PASSWORD = "Str0ng-Test-Pass!"


def png_bytes():
    raw = b"\x00\xff\xff\xff" * 1
    chunk = lambda k, d: struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)  # noqa: E731
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def png_file(name="photo.png"):
    return SimpleUploadedFile(name, png_bytes(), content_type="image/png")


def login(client, user):
    client.credentials()
    res = client.post("/api/v1/auth/token/", {"email": user.email, "password": PASSWORD}, format="json")
    assert res.status_code == 200, res.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.json()['access']}")
    return client


def make_admin(email, level):
    return User.objects.create_user(email=email, password=PASSWORD, role=Role.ADMIN, admin_level=level,
                                    is_staff=level == AdminLevel.SUPER)


def submit_kyc(user, number="12345678"):
    return KycSubmission.objects.create(
        user=user, document_type="NATIONAL_ID", document_number=number, legal_first_name=user.first_name or "A",
        legal_last_name=user.last_name or "B", date_of_birth="1990-01-01",
        id_front=png_file(), id_back=png_file(), selfie=png_file(),
    )


def ready_borrower(email="ready@example.com", income="85000", obligations="15000", reviewer=None, number="12345678"):
    """A borrower with verified contacts, a complete profile and approved identity (score 50)."""
    user = User.objects.create_user(email=email, password=PASSWORD, role=Role.BORROWER, first_name="Brenda",
                                    last_name="Wanjiru", phone_number=f"+2547{abs(hash(email)) % 10**8:08d}",
                                    is_email_verified=True, is_phone_verified=True)
    profile = get_profile(user)
    profile.employment_status = "EMPLOYED"
    profile.monthly_income = Decimal(income)
    profile.monthly_obligations = Decimal(obligations)
    profile.county = "Nairobi"
    profile.date_of_birth = "1992-04-18"
    profile.save()
    reviewer = reviewer or make_admin(f"ops-{email}", AdminLevel.OPERATIONS)
    sub = submit_kyc(user, number=number)
    kyc_services.approve(actor=reviewer, submission_id=sub.pk)
    user.refresh_from_db()
    return user


def make_guarantor(email="guarantor@example.com"):
    return User.objects.create_user(email=email, password=PASSWORD, role=Role.GUARANTOR, first_name="Grace",
                                    last_name="Mutua")
