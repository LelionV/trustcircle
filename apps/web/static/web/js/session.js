// The signed-in user and their server-computed permissions.
// The UI uses these only to decide what to show; the API enforces them.

let current = null;
let perms = new Set();

export function setUser(user) {
  current = user;
  perms = new Set(user?.permissions || []);
}

export const user = () => current;

/** True if the user has the permission, or any of them when given an array. */
export function can(permission) {
  if (!permission) return true;
  if (Array.isArray(permission)) return permission.some((p) => perms.has(p));
  return perms.has(permission);
}

export const isAdminView = () => can("admin.dashboard.view");

// Plain-language names for the permission list on the profile page.
export const PERMISSION_GROUPS = [
  ["Your account", {
    "profile.view": "See your profile",
    "profile.edit": "Update your name",
    "notifications.view": "Receive notifications",
    "kyc.submit": "Submit identity documents",
    "chat.use": "Message people on your loans",
    "users.report": "Report people",
    "disputes.raise": "Raise disputes",
  }],
  ["Borrowing", {
    "loans.apply": "Apply for loans",
    "loans.view_own": "See your loans",
    "repayments.make": "Make repayments",
    "extensions.request": "Request more time to repay",
    "trust.view_own": "See your trust score",
    "risk.view_own": "See your risk rating",
    "pricing.view": "See interest brackets",
  }],
  ["Investing", {
    "marketplace.view": "Browse loan requests",
    "investments.make": "Fund loans and make offers",
    "extensions.vote": "Agree or object to extensions on loans you fund",
    "investments.view_own": "Track your investments",
    "statements.view_own": "Download statements",
  }],
  ["Guaranteeing", {
    "guarantees.respond": "Accept or decline guarantee requests",
    "guarantees.view_own": "See your guarantees",
    "commissions.view_own": "See commission earnings",
  }],
  ["Money", {
    "wallet.view_own": "See your wallet",
    "wallet.deposit": "Deposit funds",
    "wallet.withdraw": "Withdraw funds",
    "wallet.transfer": "Transfer between wallets",
  }],
  ["Administration", {
    "admin.dashboard.view": "Open the admin overview",
    "admin.users.view": "Look up users",
    "admin.users.manage": "Edit users",
    "admin.roles.manage": "Change roles and admin levels",
    "admin.accounts.freeze": "Freeze and unfreeze accounts",
    "admin.kyc.view": "See KYC submissions",
    "admin.kyc.approve": "Approve KYC",
    "admin.loans.view": "See loan applications",
    "admin.loans.approve": "Approve or reject loans",
    "admin.loans.disburse": "Pay out funded loans",
    "admin.extensions.review": "Review extension requests",
    "admin.defaults.manage": "Manage overdue loans and defaults",
    "admin.disputes.view": "See disputes",
    "admin.disputes.manage": "Resolve disputes",
    "admin.wallets.view": "Inspect wallets",
    "admin.ledger.view": "Inspect the ledger",
    "admin.deposits.review": "Review deposits",
    "admin.withdrawals.approve": "Approve withdrawals",
    "admin.wallets.hold": "Hold and release customer funds",
    "admin.support.chat": "Answer support chats",
    "admin.moderation.view": "See user reports",
    "admin.moderation.manage": "Act on user reports",
    "admin.reconciliation.run": "Reconcile transactions",
    "admin.revenue.view": "See platform revenue",
    "admin.reports.view": "Run reports",
    "admin.config.manage": "Change rates, fees and scoring rules",
    "admin.trust.override": "Adjust trust scores (with a reason)",
    "admin.notifications.configure": "Configure notifications",
    "admin.audit.view": "Read the audit trail",
  }],
];
