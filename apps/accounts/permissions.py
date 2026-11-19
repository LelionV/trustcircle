"""
Platform permission matrix — the single source of truth for who may do what.

Permissions are derived from a user's role, admin level and account state.
The API enforces them (``apps.common.permissions.HasPlatformPermission``)
and returns them on ``/accounts/me/`` so the web and mobile clients can show
only what the user is allowed to use. Clients never decide access themselves.

Naming: ``<area>.<action>`` for users, ``admin.<area>.<action>`` for staff.
"""
from __future__ import annotations

from .models import AdminLevel, Role

# --- Everyone with an active account -------------------------------------
COMMON = frozenset({
    "profile.view",
    "profile.edit",
    "notifications.view",
})

# Customers (not staff) can raise a dispute about anything on their account.
CUSTOMER = frozenset({"disputes.raise", "chat.use", "users.report"})

# --- Customer roles ------------------------------------------------------
WALLET = frozenset({"wallet.view_own", "wallet.deposit", "wallet.withdraw", "wallet.transfer"})
KYC = frozenset({"kyc.submit"})

BORROWER = frozenset({
    "loans.apply",
    "loans.view_own",
    "repayments.make",
    "extensions.request",
    "statements.view_own",
    "trust.view_own",
    "risk.view_own",
    "pricing.view",
}) | WALLET | KYC | CUSTOMER

INVESTOR = frozenset({
    "marketplace.view",
    "investments.make",
    "investments.view_own",
    "extensions.vote",
    "statements.view_own",
    "pricing.view",
}) | WALLET | KYC | CUSTOMER

# A guarantor can also invest (but never in a loan they guarantee; the services enforce that).
GUARANTOR = frozenset({
    "guarantees.respond",
    "statements.view_own",
    "guarantees.view_own",
    "commissions.view_own",
}) | INVESTOR | WALLET | KYC | CUSTOMER

ROLE_PERMISSIONS = {
    Role.BORROWER: BORROWER,
    Role.INVESTOR: INVESTOR,
    Role.GUARANTOR: GUARANTOR,
    Role.ADMIN: frozenset(),
}

# --- Administrator levels ------------------------------------------------
ADMIN_SUPPORT = frozenset({
    "admin.dashboard.view",
    "admin.users.view",
    "admin.kyc.view",
    "admin.loans.view",
    "admin.disputes.view",
    "admin.audit.view",
    "admin.wallets.view",
    "admin.support.chat",
    "admin.moderation.view",
    "pricing.view",
})

ADMIN_OPERATIONS = ADMIN_SUPPORT | frozenset({
    "admin.kyc.approve",
    "admin.loans.approve",
    "admin.loans.disburse",
    "admin.extensions.review",
    "admin.defaults.manage",
    "admin.disputes.manage",
    "admin.accounts.freeze",
    "admin.risk.override",
    "admin.moderation.manage",
    "admin.notifications.configure",
})

ADMIN_FINANCE = ADMIN_SUPPORT | frozenset({
    "admin.wallets.view",
    "admin.ledger.view",
    "admin.deposits.review",
    "admin.withdrawals.approve",
    "admin.reconciliation.run",
    "admin.revenue.view",
    "admin.reports.view",
    "admin.accounts.freeze",
    "admin.wallets.hold",
    "admin.loans.disburse",
})

ADMIN_SUPER = ADMIN_OPERATIONS | ADMIN_FINANCE | frozenset({
    "admin.users.manage",
    "admin.roles.manage",
    "admin.config.manage",
    "admin.trust.override",
})

ADMIN_LEVEL_PERMISSIONS = {
    AdminLevel.NONE: frozenset(),
    AdminLevel.SUPPORT: ADMIN_SUPPORT,
    AdminLevel.OPERATIONS: ADMIN_OPERATIONS,
    AdminLevel.FINANCE: ADMIN_FINANCE,
    AdminLevel.SUPER: ADMIN_SUPER,
}

# A frozen account can still look around and pay what it owes, but it
# cannot move money out or take on new positions.
BLOCKED_WHEN_FROZEN = frozenset({
    "wallet.withdraw",
    "wallet.transfer",
    "investments.make",
    "loans.apply",
    "guarantees.respond",
})

ALL_PERMISSIONS = (
    COMMON | CUSTOMER | BORROWER | INVESTOR | GUARANTOR | ADMIN_SUPER
)


def permissions_for(user) -> frozenset[str]:
    if user is None or not user.is_authenticated or not user.is_active:
        return frozenset()
    perms = set(COMMON)
    perms |= ROLE_PERMISSIONS.get(user.role, frozenset())
    if user.role == Role.ADMIN:
        perms |= ADMIN_LEVEL_PERMISSIONS.get(user.admin_level, frozenset())
    if user.is_frozen:
        perms -= BLOCKED_WHEN_FROZEN
    return frozenset(perms)


def has_permission(user, permission: str) -> bool:
    return permission in permissions_for(user)
