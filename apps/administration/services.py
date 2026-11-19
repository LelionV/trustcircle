from django.db import transaction

from apps.accounts.models import AdminLevel, Role, User
from apps.accounts.permissions import has_permission
from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation


@transaction.atomic
def set_account_frozen(*, actor: User, target_id, frozen: bool, reason: str, request=None) -> User:
    """Freeze or unfreeze an account. Always audited; never silent."""
    target = User.objects.select_for_update().get(pk=target_id)

    if target.pk == actor.pk:
        raise BusinessRuleViolation("You cannot freeze or unfreeze your own account.", code="self_action")
    if target.role == Role.ADMIN and not has_permission(actor, "admin.users.manage"):
        raise BusinessRuleViolation(
            "Only a super administrator can freeze or unfreeze another administrator.",
            code="admin_target",
        )
    if target.is_frozen == frozen:
        state = "frozen" if frozen else "active"
        raise BusinessRuleViolation(f"This account is already {state}.", code="no_change")

    target.is_frozen = frozen
    target.save(update_fields=["is_frozen", "updated_at"])
    audit.record(
        action="user.account.frozen" if frozen else "user.account.unfrozen",
        entity_type="User",
        entity_id=target.pk,
        actor=actor,
        before={"is_frozen": not frozen},
        after={"is_frozen": frozen},
        reason=reason,
        request=request,
    )
    return target


@transaction.atomic
def change_role(*, actor, target_id, role, admin_level, reason, request=None):
    """Change a user's role and admin level (super admins only). Always audited."""
    target = User.objects.select_for_update().get(pk=target_id)
    if target.pk == actor.pk:
        raise BusinessRuleViolation("You can't change your own role.", code="self_action")
    if role != Role.ADMIN:
        admin_level = AdminLevel.NONE
    elif admin_level == AdminLevel.NONE:
        raise BusinessRuleViolation("Choose an admin level for an administrator.", code="admin_level_required")
    if target.role == role and target.admin_level == admin_level:
        raise BusinessRuleViolation("That's already this user's role.", code="no_change")
    losing_super = target.admin_level == AdminLevel.SUPER and admin_level != AdminLevel.SUPER
    if losing_super:
        others = User.objects.filter(role=Role.ADMIN, admin_level=AdminLevel.SUPER, is_active=True).exclude(pk=target.pk)
        if not others.exists():
            raise BusinessRuleViolation("The platform needs at least one super admin.", code="last_super_admin")

    before = {"role": target.role, "admin_level": target.admin_level, "is_staff": target.is_staff,
              "is_superuser": target.is_superuser}
    target.role = role
    target.admin_level = admin_level
    # Only super admins may use Django's own admin site.
    target.is_staff = target.is_superuser = admin_level == AdminLevel.SUPER
    target.save(update_fields=["role", "admin_level", "is_staff", "is_superuser", "updated_at"])
    audit.record(
        action="user.role.changed",
        entity_type="User",
        entity_id=target.pk,
        actor=actor,
        before=before,
        after={"role": role, "admin_level": admin_level, "is_staff": target.is_staff,
               "is_superuser": target.is_superuser},
        reason=reason,
        request=request,
    )
    return target
