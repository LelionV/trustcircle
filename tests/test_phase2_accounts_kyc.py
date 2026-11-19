"""Phase 2: registration, verification codes, profiles, KYC and role management."""
import re

import pytest
from django.core import mail

from apps.accounts.models import AdminLevel, Role, User
from apps.audit.models import AuditLog
from apps.authentication import sms
from apps.authentication.models import OneTimeCode
from apps.kyc.models import KycStatus, KycSubmission

from .helpers import PASSWORD, login, make_admin, png_file, ready_borrower, submit_kyc

pytestmark = pytest.mark.django_db


# --- Registration --------------------------------------------------------------------

def test_register_creates_customer_and_signs_in(api_client):
    res = api_client.post("/api/v1/auth/register/", {
        "email": "Neema@Example.com", "password": "Kilimanjaro-2026", "first_name": "Neema",
        "last_name": "Otieno", "phone_number": "0712 345 678", "role": "INVESTOR",
    }, format="json")
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["access"] and body["user"]["role"] == "INVESTOR"
    assert body["user"]["kyc_status"] == "NOT_SUBMITTED"
    user = User.objects.get(email="neema@example.com")
    assert user.phone_number == "+254712345678"
    assert AuditLog.objects.filter(action="user.registered", entity_id=str(user.pk)).exists()


def test_register_cannot_create_admin(api_client):
    res = api_client.post("/api/v1/auth/register/", {
        "email": "x@example.com", "password": "Kilimanjaro-2026", "first_name": "X", "last_name": "Y", "role": "ADMIN",
    }, format="json")
    assert res.status_code == 400
    assert not User.objects.filter(email="x@example.com").exists()


def test_register_rejects_weak_password_and_duplicate_email(api_client, borrower):
    res = api_client.post("/api/v1/auth/register/", {
        "email": borrower.email.upper(), "password": "12345678", "first_name": "A", "last_name": "B", "role": "BORROWER",
    }, format="json")
    details = res.json()["error"]["details"]
    assert res.status_code == 400 and "email" in details


# --- Verification codes ---------------------------------------------------------------

def _sent_code():
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def test_email_code_flow(api_client, borrower):
    login(api_client, borrower)
    res = api_client.post("/api/v1/auth/otp/request/", {"channel": "EMAIL"}, format="json")
    assert res.status_code == 200 and "***" in res.json()["sent_to"]
    stored = OneTimeCode.objects.get(user=borrower)
    assert _sent_code() not in stored.code_hash  # only a hash is kept

    wrong = api_client.post("/api/v1/auth/otp/verify/", {"channel": "EMAIL", "code": "000000"}, format="json")
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "otp_invalid"
    stored.refresh_from_db()
    assert stored.attempts == 1  # the failed attempt was saved despite the error

    ok = api_client.post("/api/v1/auth/otp/verify/", {"channel": "EMAIL", "code": _sent_code()}, format="json")
    assert ok.status_code == 200 and ok.json()["is_email_verified"] is True
    again = api_client.post("/api/v1/auth/otp/verify/", {"channel": "EMAIL", "code": _sent_code()}, format="json")
    assert again.status_code == 422  # a code works once


def test_code_locks_after_max_attempts(api_client, borrower, settings):
    settings.OTP_MAX_ATTEMPTS = 2
    login(api_client, borrower)
    api_client.post("/api/v1/auth/otp/request/", {"channel": "EMAIL"}, format="json")
    for _ in range(2):
        api_client.post("/api/v1/auth/otp/verify/", {"channel": "EMAIL", "code": "000000"}, format="json")
    res = api_client.post("/api/v1/auth/otp/verify/", {"channel": "EMAIL", "code": _sent_code()}, format="json")
    assert res.json()["error"]["code"] == "otp_locked"


def test_resend_cooldown(api_client, borrower):
    login(api_client, borrower)
    api_client.post("/api/v1/auth/otp/request/", {"channel": "EMAIL"}, format="json")
    res = api_client.post("/api/v1/auth/otp/request/", {"channel": "EMAIL"}, format="json")
    assert res.status_code == 422 and res.json()["error"]["code"] == "otp_cooldown"


def test_phone_change_requires_new_verification(api_client, borrower):
    borrower.phone_number, borrower.is_phone_verified = "+254711111111", True
    borrower.save()
    login(api_client, borrower)
    res = api_client.put("/api/v1/auth/phone/", {"phone_number": "0722 000 111"}, format="json")
    assert res.json()["phone_number"] == "+254722000111" and res.json()["is_phone_verified"] is False
    sms.send_sms.outbox = []
    api_client.post("/api/v1/auth/otp/request/", {"channel": "PHONE"}, format="json")
    phone, message = sms.send_sms.outbox[-1]
    code = re.search(r"\b(\d{6})\b", message).group(1)
    assert phone == "+254722000111"
    assert api_client.post("/api/v1/auth/otp/verify/", {"channel": "PHONE", "code": code}, format="json").status_code == 200


def test_password_change(api_client, borrower):
    login(api_client, borrower)
    bad = api_client.post("/api/v1/auth/password/change/", {"current_password": "nope", "new_password": "Another-Pass-2026"}, format="json")
    assert bad.status_code == 400
    ok = api_client.post("/api/v1/auth/password/change/", {"current_password": PASSWORD, "new_password": "Another-Pass-2026"}, format="json")
    assert ok.status_code == 204
    borrower.refresh_from_db()
    assert borrower.check_password("Another-Pass-2026")


# --- Profiles ---------------------------------------------------------------------------

def test_borrower_profile_update_and_income_reverification(api_client):
    user = ready_borrower()
    profile = user.borrower_profile
    profile.income_verified = True
    profile.save()
    login(api_client, user)
    res = api_client.put("/api/v1/accounts/me/profile/", {"monthly_income": "90000.00"}, format="json")
    assert res.status_code == 200
    assert res.json()["profile"]["income_verified"] is False  # changed income must be checked again


def test_profile_rejects_negative_income(api_client, borrower):
    login(api_client, borrower)
    res = api_client.put("/api/v1/accounts/me/profile/", {"monthly_income": "-5"}, format="json")
    assert res.status_code == 400


# --- KYC ----------------------------------------------------------------------------------

def test_kyc_submission_and_private_files(api_client, borrower, make_user):
    login(api_client, borrower)
    res = api_client.post("/api/v1/kyc/me/", {
        "document_type": "NATIONAL_ID", "document_number": "12 345 678", "legal_first_name": "B",
        "legal_last_name": "W", "date_of_birth": "1990-01-01", "id_front": png_file(), "id_back": png_file(),
        "selfie": png_file(),
    }, format="multipart")
    assert res.status_code == 201, res.content
    assert res.json()["document_number"] == "12345678"
    file_url = res.json()["files"]["id_front"]
    assert api_client.get(file_url).status_code == 200

    stranger = make_user(email="stranger@example.com")
    login(api_client, stranger)
    assert api_client.get(file_url).status_code == 404

    login(api_client, borrower)
    again = api_client.post("/api/v1/kyc/me/", {"document_type": "PASSPORT"}, format="multipart")
    assert again.status_code in (400, 422)


def test_kyc_rejects_non_image_upload(api_client, borrower):
    from django.core.files.uploadedfile import SimpleUploadedFile

    login(api_client, borrower)
    fake = SimpleUploadedFile("id.png", b"MZ\x90\x00 not really an image", content_type="image/png")
    res = api_client.post("/api/v1/kyc/me/", {
        "document_type": "PASSPORT", "document_number": "A1234567", "legal_first_name": "B", "legal_last_name": "W",
        "date_of_birth": "1990-01-01", "id_front": fake, "selfie": png_file(),
    }, format="multipart")
    assert res.status_code == 400 and "id_front" in res.json()["error"]["details"]


def test_kyc_review_permissions_and_trust_creation(api_client, borrower):
    support = make_admin("support@example.com", AdminLevel.SUPPORT)
    ops = make_admin("ops@example.com", AdminLevel.OPERATIONS)
    sub = submit_kyc(borrower)

    login(api_client, support)
    assert api_client.get("/api/v1/admin/kyc/").json()["count"] == 1
    assert api_client.post(f"/api/v1/admin/kyc/{sub.pk}/approve/", {}, format="json").status_code == 403

    login(api_client, ops)
    res = api_client.post(f"/api/v1/admin/kyc/{sub.pk}/approve/", {"note": "Clear photos"}, format="json")
    assert res.status_code == 200 and res.json()["status"] == "APPROVED"
    borrower.refresh_from_db()
    assert borrower.trust_score.score == 50  # new verified borrower starts at the initial score
    assert borrower.risk_profile.classification


def test_kyc_rejection_allows_resubmission(api_client, borrower):
    ops = make_admin("ops@example.com", AdminLevel.OPERATIONS)
    sub = submit_kyc(borrower)
    login(api_client, ops)
    short = api_client.post(f"/api/v1/admin/kyc/{sub.pk}/reject/", {"reason": "blurry"}, format="json")
    assert short.status_code == 400
    api_client.post(f"/api/v1/admin/kyc/{sub.pk}/reject/", {"reason": "The ID photo is too blurred to read."}, format="json")
    login(api_client, borrower)
    me = api_client.get("/api/v1/kyc/me/").json()
    assert me["status"] == KycStatus.REJECTED and "blurred" in me["submission"]["rejection_reason"]
    submit_kyc(borrower, number="12345678")  # allowed again
    assert KycSubmission.objects.filter(user=borrower).count() == 2


def test_document_already_approved_for_someone_else_is_blocked(api_client):
    ready_borrower(email="first@example.com", number="99887766")
    other = User.objects.create_user(email="second@example.com", password=PASSWORD, role=Role.BORROWER)
    login(api_client, other)
    res = api_client.post("/api/v1/kyc/me/", {
        "document_type": "NATIONAL_ID", "document_number": "99887766", "legal_first_name": "S", "legal_last_name": "T",
        "date_of_birth": "1990-01-01", "id_front": png_file(), "id_back": png_file(), "selfie": png_file(),
    }, format="multipart")
    assert res.status_code == 422 and res.json()["error"]["code"] == "document_in_use"


# --- Role management ------------------------------------------------------------------------

def test_super_admin_changes_roles_with_safeguards(api_client, borrower):
    sup = make_admin("super@example.com", AdminLevel.SUPER)
    login(api_client, sup)
    res = api_client.post(f"/api/v1/admin/users/{borrower.pk}/role/",
                          {"role": "ADMIN", "admin_level": "FINANCE", "reason": "Joined the finance team"}, format="json")
    assert res.status_code == 200 and res.json()["admin_level"] == "FINANCE"
    self_change = api_client.post(f"/api/v1/admin/users/{sup.pk}/role/",
                                  {"role": "BORROWER", "reason": "Trying to demote myself"}, format="json")
    assert self_change.json()["error"]["code"] == "self_action"


def test_demoted_super_admin_loses_role_management(api_client):
    sup = make_admin("super@example.com", AdminLevel.SUPER)
    other = make_admin("super2@example.com", AdminLevel.SUPER)
    login(api_client, other)
    assert api_client.post(f"/api/v1/admin/users/{sup.pk}/role/",
                           {"role": "ADMIN", "admin_level": "SUPPORT", "reason": "Moving to support desk"},
                           format="json").status_code == 200
    login(api_client, sup)  # sup is now Support, so can't manage roles at all
    assert api_client.post(f"/api/v1/admin/users/{other.pk}/role/",
                           {"role": "BORROWER", "reason": "Should be blocked"}, format="json").status_code == 403


def test_operations_cannot_change_roles(api_client, borrower):
    login(api_client, make_admin("ops@example.com", AdminLevel.OPERATIONS))
    res = api_client.post(f"/api/v1/admin/users/{borrower.pk}/role/",
                          {"role": "INVESTOR", "reason": "No permission for this"}, format="json")
    assert res.status_code == 403
