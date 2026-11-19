"""
Development demo data (DEBUG only):

    python manage.py seed_demo_data

* creates the demo users (same as seed_dev_users)
* verifies their email and phone, fills in their profiles
* approves identity documents for the demo borrower, investor and guarantor
  (the "documents" are blank placeholder images)
* adds two more borrowers whose documents wait in the KYC review queue
* creates the default loan product and interest brackets

It never invents repayment history. To see trust scores move, use
`python manage.py simulate_repayments`.
"""
import struct
import zlib
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.accounts.profiles import get_profile
from apps.kyc.models import KycStatus, KycSubmission
from apps.loans.pricing import active_bracket_set
from apps.loans.services import default_product
from apps.risk_engine.services import assess_risk
from apps.trust_engine.services import recalculate_trust


def placeholder_png(width=480, height=300, rgb=(222, 226, 220)):
    """A plain grey PNG so demo KYC records have real image files."""
    row = b"\x00" + bytes(rgb) * width
    raw = row * height

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


PROFILES = {
    "borrower@p2plend.local": {"county": "Nairobi", "town": "Westlands", "employment_status": "EMPLOYED",
                               "employer_name": "Savanna Logistics", "monthly_income": Decimal("85000"),
                               "monthly_obligations": Decimal("18000"), "date_of_birth": "1992-04-18"},
    "guarantor@p2plend.local": {"county": "Kiambu", "town": "Thika", "employment_status": "SELF_EMPLOYED",
                                "employer_name": "Mutua Hardware", "monthly_income": Decimal("140000"),
                                "date_of_birth": "1985-09-02"},
    "investor@p2plend.local": {"county": "Mombasa", "town": "Nyali", "occupation": "Engineer",
                               "source_of_funds": "SALARY", "date_of_birth": "1988-01-25"},
}
EXTRA_BORROWERS = [
    ("mercy.atieno@example.co.ke", "Mercy", "Atieno", "+254711000101"),
    ("daniel.mwangi@example.co.ke", "Daniel", "Mwangi", "+254711000102"),
]


class Command(BaseCommand):
    help = "Create demo users, profiles and identity checks for local development."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="DevPass#2026")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo_data only runs with DEBUG=True.")
        call_command("seed_dev_users", password=options["password"], stdout=self.stdout)
        reviewer = User.objects.filter(email="operations@p2plend.local").first()
        default_product()
        active_bracket_set()

        for i, (email, details) in enumerate(PROFILES.items(), start=1):
            user = User.objects.get(email=email)
            self._verify_contacts(user, f"+25470000000{i}")
            profile = get_profile(user)
            for key, value in details.items():
                setattr(profile, key, value)
            if user.role in (Role.BORROWER, Role.GUARANTOR):
                profile.income_verified = True
                profile.income_verified_at = timezone.now()
            profile.save()
            self._kyc(user, KycStatus.APPROVED, reviewer, f"2{i}345678")
            recalculate_trust(user, reason="Demo data: identity verified")
            assess_risk(user, reason="Demo data")
            self.stdout.write(self.style.SUCCESS(f"  ready    {email}"))

        for n, (email, first, last, phone) in enumerate(EXTRA_BORROWERS, start=1):
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email=email, password=options["password"], role=Role.BORROWER,
                                                first_name=first, last_name=last)
            self._verify_contacts(user, phone)
            profile = get_profile(user)
            profile.county, profile.employment_status = "Nakuru", "EMPLOYED"
            profile.monthly_income, profile.monthly_obligations = Decimal("42000") * n, Decimal("9000")
            profile.save()
            self._kyc(user, KycStatus.PENDING, None, f"3{n}456789")
            self.stdout.write(self.style.SUCCESS(f"  waiting  {email} (documents in the KYC queue)"))

        self._demo_money()
        self.stdout.write("\nDone. Sign in as operations@p2plend.local to review the KYC queue.")

    def _demo_money(self):
        """Sandbox deposits so the demo investor and guarantor can invest and guarantee (labelled as sandbox)."""
        if not getattr(settings, "SANDBOX_PAYMENTS_ENABLED", False):
            self.stdout.write("  (sandbox payments are off: no demo wallet balances)")
            return
        from apps.accounting.services import balances
        from apps.payments import services as payments

        for email, amount in (("investor@p2plend.local", "200000"), ("guarantor@p2plend.local", "60000")):
            user = User.objects.get(email=email)
            if balances(user)["available"] > 0:
                continue
            intent = payments.start_deposit(user, amount=Decimal(amount), provider="SANDBOX",
                                            idempotency_key="seed-demo-deposit")
            payments.settle(intent.provider_reference, succeeded=True, amount=Decimal(amount),
                            raw={"seed_demo_data": True})
            self.stdout.write(self.style.SUCCESS(f"  wallet   {email}: KES {Decimal(amount):,.2f} (sandbox deposit)"))

    @staticmethod
    def _verify_contacts(user, phone):
        if not user.phone_number and not User.objects.filter(phone_number=phone).exists():
            user.phone_number = phone
        user.is_email_verified = True
        user.is_phone_verified = bool(user.phone_number)
        user.save()

    @staticmethod
    def _kyc(user, status, reviewer, number):
        if user.kyc_submissions.exists():
            return
        image = placeholder_png()
        submission = KycSubmission(
            user=user, document_type="NATIONAL_ID", document_number=number,
            legal_first_name=user.first_name, legal_last_name=user.last_name or "Demo",
            date_of_birth="1990-01-01", status=status,
        )
        for field in ("id_front", "id_back", "selfie"):
            getattr(submission, field).save(f"{field}.png", ContentFile(image), save=False)
        if status == KycStatus.APPROVED:
            submission.reviewed_by = reviewer
            submission.reviewed_at = timezone.now()
            submission.review_note = "Demo data"
        submission.save()
