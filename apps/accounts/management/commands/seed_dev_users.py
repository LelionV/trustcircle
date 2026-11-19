"""
Create one demo user per role for local development.

    python manage.py seed_dev_users
    python manage.py seed_dev_users --password "MyStr0ngPass!"

Refuses to run when DEBUG is False so it can never touch production.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import AdminLevel, Role, User

DEMO_USERS = [
    ("borrower@p2plend.local", Role.BORROWER, AdminLevel.NONE, "Brenda", "Borrower"),
    ("investor@p2plend.local", Role.INVESTOR, AdminLevel.NONE, "Ian", "Investor"),
    ("guarantor@p2plend.local", Role.GUARANTOR, AdminLevel.NONE, "Grace", "Guarantor"),
    ("support@p2plend.local", Role.ADMIN, AdminLevel.SUPPORT, "Sam", "Support"),
    ("operations@p2plend.local", Role.ADMIN, AdminLevel.OPERATIONS, "Olive", "Operations"),
    ("finance@p2plend.local", Role.ADMIN, AdminLevel.FINANCE, "Faith", "Finance"),
    ("admin@p2plend.local", Role.ADMIN, AdminLevel.SUPER, "Ada", "Admin"),
]


class Command(BaseCommand):
    help = "Create demo users (one per role) for local development."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="DevPass#2026", help="Password for every demo user.")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_dev_users only runs with DEBUG=True.")

        password = options["password"]
        for email, role, level, first, last in DEMO_USERS:
            user = User.objects.filter(email=email).first()
            if user:
                self.stdout.write(f"  exists   {email}")
                continue
            is_admin = level == AdminLevel.SUPER
            User.objects.create_user(
                email=email,
                password=password,
                role=role,
                admin_level=level,
                first_name=first,
                last_name=last,
                is_staff=is_admin,
                is_superuser=is_admin,
                is_email_verified=True,
            )
            self.stdout.write(self.style.SUCCESS(f"  created  {email}  ({role})"))

        self.stdout.write(f"\nPassword for new demo users: {password}")
