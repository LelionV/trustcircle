"""Kenyan-first phone number normalisation to E.164 (+2547XXXXXXXX)."""
import re


class PhoneNumberError(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    """
    '0712 345 678' -> '+254712345678', '254712345678' -> '+254712345678'.
    Other countries must be given in +<country code> form.
    """
    if raw is None:
        raise PhoneNumberError("Enter a phone number.")
    digits = re.sub(r"[\s\-()]", "", str(raw))
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if re.fullmatch(r"0[17]\d{8}", digits):
        digits = "+254" + digits[1:]
    elif re.fullmatch(r"254[17]\d{8}", digits):
        digits = "+" + digits
    if not re.fullmatch(r"\+[1-9]\d{7,14}", digits):
        raise PhoneNumberError("Enter a phone number like 0712 345 678 or +254712345678.")
    return digits


def mask_phone(phone: str) -> str:
    return phone[:-6] + "***" + phone[-3:] if phone and len(phone) > 8 else phone


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "***@" + domain) if domain else email
