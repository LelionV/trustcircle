"""
Platform user.

Phase 1 establishes the custom user model (it must exist before the first
migration). Registration, OTP verification, KYC and full role management
are built on top of it in Phase 2.
"""
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Role(models.TextChoices):
    BORROWER = "BORROWER", "Borrower"
    INVESTOR = "INVESTOR", "Lender / Investor"
    GUARANTOR = "GUARANTOR", "Guarantor"
    ADMIN = "ADMIN", "Administrator"


class AdminLevel(models.TextChoices):
    """Administrator permission tiers (only meaningful when role == ADMIN)."""

    NONE = "NONE", "Not an administrator"
    SUPPORT = "SUPPORT", "Support (read-only, user assistance)"
    OPERATIONS = "OPERATIONS", "Operations (KYC, loan review)"
    FINANCE = "FINANCE", "Finance (withdrawals, reconciliation)"
    SUPER = "SUPER", "Super administrator (configuration)"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", Role.BORROWER)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", Role.ADMIN)
        extra_fields.setdefault("admin_level", AdminLevel.SUPER)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("email address", unique=True)
    phone_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True,
        help_text="E.164 format, e.g. +254712345678",
    )
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.BORROWER, db_index=True)
    admin_level = models.CharField(max_length=20, choices=AdminLevel.choices, default=AdminLevel.NONE)

    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Can log in to the Django admin site.")
    is_frozen = models.BooleanField(
        default=False, help_text="Frozen accounts cannot move money (set by administrators)."
    )

    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["-date_joined"]
        constraints = [
            models.CheckConstraint(
                name="accounts_user_admin_level_only_for_admins",
                condition=Q(role="ADMIN") | Q(admin_level="NONE"),
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.email

    @property
    def is_platform_admin(self) -> bool:
        return self.role == Role.ADMIN and self.admin_level != AdminLevel.NONE
