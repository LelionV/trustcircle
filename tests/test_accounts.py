import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import AdminLevel, Role, User

pytestmark = pytest.mark.django_db


def test_email_is_normalised_and_unique():
    User.objects.create_user(email="Jane@Example.COM", password="x-Pass-12345")
    assert User.objects.filter(email="jane@example.com").exists()
    with pytest.raises(ValidationError):
        User.objects.create_user(email="JANE@example.com", password="x-Pass-12345")


def test_superuser_is_super_admin():
    admin = User.objects.create_superuser(email="root@example.com", password="x-Pass-12345")
    assert admin.role == Role.ADMIN
    assert admin.admin_level == AdminLevel.SUPER
    assert admin.is_platform_admin


def test_admin_level_requires_admin_role_in_model_validation():
    with pytest.raises(ValidationError):
        User.objects.create_user(
            email="b@example.com", password="x-Pass-12345",
            role=Role.BORROWER, admin_level=AdminLevel.FINANCE,
        )


def test_admin_level_constraint_is_enforced_by_database():
    user = User.objects.create_user(email="c@example.com", password="x-Pass-12345")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(admin_level=AdminLevel.SUPER)


def test_seed_dev_users_command(settings):
    from django.core.management import call_command

    settings.DEBUG = True
    call_command("seed_dev_users")
    assert set(User.objects.values_list("role", flat=True)) == {r.value for r in Role}
    call_command("seed_dev_users")  # idempotent
    assert User.objects.count() == 4
