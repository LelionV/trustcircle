"""Registration and email/phone verification."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation
from apps.common.phone import mask_email, mask_phone

from .models import OneTimeCode, OtpChannel
from .sms import send_sms


def _generate_code() -> str:
    length = getattr(settings, "OTP_LENGTH", 6)
    return "".join(secrets.choice("0123456789") for _ in range(length))


@transaction.atomic
def register_user(*, email, password, role, first_name, last_name, phone_number=None, request=None) -> User:
    user = User.objects.create_user(
        email=email,
        password=password,
        role=role,
        first_name=first_name,
        last_name=last_name,
        phone_number=phone_number,
    )
    audit.record(
        action="user.registered",
        entity_type="User",
        entity_id=user.pk,
        actor=user,
        after={"email": user.email, "role": user.role},
        request=request,
    )
    return user


def _destination(user, channel):
    if channel == OtpChannel.EMAIL:
        if user.is_email_verified:
            raise BusinessRuleViolation("Your email address is already verified.", code="already_verified")
        return user.email
    if not user.phone_number:
        raise BusinessRuleViolation("Add a phone number to your profile first.", code="no_phone")
    if user.is_phone_verified:
        raise BusinessRuleViolation("Your phone number is already verified.", code="already_verified")
    return user.phone_number


@transaction.atomic
def request_code(user, channel) -> dict:
    """Create and send a new code. Earlier unused codes for the channel stop working."""
    destination = _destination(user, channel)
    now = timezone.now()
    recent = OneTimeCode.objects.filter(user=user, channel=channel, created_at__gte=now - timedelta(hours=1))
    latest = recent.first()
    resend_after = getattr(settings, "OTP_RESEND_SECONDS", 60)
    if latest and (now - latest.created_at).total_seconds() < resend_after:
        wait = int(resend_after - (now - latest.created_at).total_seconds()) + 1
        raise BusinessRuleViolation(f"Wait {wait} seconds before asking for another code.", code="otp_cooldown",
                                    extra={"retry_after": wait})
    if recent.count() >= getattr(settings, "OTP_MAX_PER_HOUR", 5):
        raise BusinessRuleViolation("Too many codes requested. Try again in an hour.", code="otp_limit")

    OneTimeCode.objects.filter(user=user, channel=channel, consumed_at__isnull=True).update(consumed_at=now)
    code = _generate_code()
    ttl = getattr(settings, "OTP_TTL_MINUTES", 10)
    OneTimeCode.objects.create(
        user=user,
        channel=channel,
        destination=destination,
        code_hash=make_password(code),
        expires_at=now + timedelta(minutes=ttl),
    )
    message = f"Your P2P Lend verification code is {code}. It expires in {ttl} minutes. Never share it."
    if channel == OtpChannel.EMAIL:
        send_mail("Your P2P Lend verification code", message, None, [destination])
        sent_to = mask_email(destination)
    else:
        send_sms(destination, message)
        sent_to = mask_phone(destination)
    return {"channel": channel, "sent_to": sent_to, "expires_in_minutes": ttl}


def verify_code(user, channel, code, request=None) -> User:
    """
    Check a code. Failed attempts are committed before the error is raised,
    so the attempt limit can't be bypassed by the rollback.
    """
    outcome, detail = _check_code(user, channel, str(code).strip(), request)
    if outcome == "ok":
        return detail
    messages = {
        "expired": "This code has expired. Ask for a new one.",
        "locked": "Too many wrong attempts. Ask for a new code.",
        "changed": "Your details changed since this code was sent. Ask for a new one.",
    }
    if outcome == "invalid":
        left = detail
        message = (f"That code isn't right. {left} attempt{'s' if left != 1 else ''} left."
                   if left else "That code isn't right. Ask for a new code.")
        raise BusinessRuleViolation(message, code="otp_invalid")
    raise BusinessRuleViolation(messages[outcome], code="otp_locked" if outcome == "locked" else "otp_expired")


@transaction.atomic
def _check_code(user, channel, code, request):
    now = timezone.now()
    otp = (
        OneTimeCode.objects.select_for_update()
        .filter(user=user, channel=channel, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if otp is None or otp.expires_at <= now:
        return "expired", None
    max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
    if otp.attempts >= max_attempts:
        return "locked", None

    current_destination = user.email if channel == OtpChannel.EMAIL else user.phone_number
    if otp.destination != current_destination:
        otp.consumed_at = now
        otp.save(update_fields=["consumed_at"])
        return "changed", None

    if not check_password(code, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return "invalid", max_attempts - otp.attempts

    otp.consumed_at = now
    otp.save(update_fields=["consumed_at"])
    field = "is_email_verified" if channel == OtpChannel.EMAIL else "is_phone_verified"
    setattr(user, field, True)
    user.save(update_fields=[field, "updated_at"])
    audit.record(
        action=f"user.{channel.lower()}.verified",
        entity_type="User",
        entity_id=user.pk,
        actor=user,
        after={field: True, "destination": otp.destination},
        request=request,
    )
    return "ok", user


@transaction.atomic
def change_phone(user, phone_number, request=None) -> User:
    if User.objects.filter(phone_number=phone_number).exclude(pk=user.pk).exists():
        raise BusinessRuleViolation("This phone number is already registered to another account.",
                                    code="phone_taken")
    before = {"phone_number": user.phone_number, "is_phone_verified": user.is_phone_verified}
    if user.phone_number == phone_number:
        return user
    user.phone_number = phone_number
    user.is_phone_verified = False
    user.save(update_fields=["phone_number", "is_phone_verified", "updated_at"])
    audit.record(action="user.phone.changed", entity_type="User", entity_id=user.pk, actor=user,
                 before=before, after={"phone_number": phone_number, "is_phone_verified": False}, request=request)
    return user
