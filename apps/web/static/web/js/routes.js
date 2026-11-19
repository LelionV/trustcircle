// Every page in the web app, the permission it needs and where it sits in the
// sidebar. Paths may contain ":id". Hidden routes (detail pages) highlight
// their parent in the menu. `badge` names a counter from notifications/unread/.

import { auditView } from "./views/admin-audit.js";
import { adminConfigView } from "./views/admin-config.js";
import { adminIntegrationsView } from "./views/admin-integrations.js";
import { adminTermsView } from "./views/admin-terms.js";
import { adminKycDetailView, adminKycListView } from "./views/admin-kyc.js";
import { adminLoanDetailView, adminLoanListView } from "./views/admin-loans.js";
import { adminDisputesView, adminModerationView } from "./views/admin-moderation.js";
import { adminFinanceView, adminWithdrawalsView } from "./views/admin-money.js";
import { adminDefaultsView, adminExtensionsView } from "./views/admin-ops.js";
import { adminReportsView } from "./views/admin-reports.js";
import { usersView } from "./views/admin-users.js";
import { applyView } from "./views/apply.js";
import { chatListView, chatView } from "./views/chat.js";
import { dashboardView } from "./views/dashboard.js";
import { disputesView } from "./views/disputes.js";
import { commissionsView, guaranteesView } from "./views/guarantees.js";
import { kycView } from "./views/kyc.js";
import { loanDetailView, myLoansView } from "./views/loans.js";
import { marketplaceView } from "./views/marketplace.js";
import { notificationsView } from "./views/notifications.js";
import { portfolioView } from "./views/portfolio.js";
import { profileView } from "./views/profile.js";
import { repaymentsView } from "./views/repayments.js";
import { statementsView } from "./views/statements.js";
import { trustView } from "./views/trust.js";
import { walletView } from "./views/wallet.js";

export const SECTIONS = ["", "Borrowing", "Investing", "Guarantees", "Money", "Administration", "Account"];

export const ROUTES = [
  { path: "/", title: "Dashboard", section: "", icon: "home", render: dashboardView },
  { path: "/chat", title: "Messages", section: "", icon: "chat", perm: ["chat.use", "admin.support.chat"], render: chatListView, badge: "chat" },
  { path: "/chat/:id", title: "Conversation", hidden: true, parent: "/chat", perm: ["chat.use", "admin.support.chat", "admin.moderation.view"], render: chatView },

  // Borrowing
  { path: "/loans", title: "My loans", section: "Borrowing", icon: "loan", perm: "loans.view_own", render: myLoansView },
  { path: "/loans/:id", title: "Loan", hidden: true, parent: "/loans", perm: "loans.view_own", render: loanDetailView },
  { path: "/apply", title: "Apply for a loan", section: "Borrowing", icon: "apply", perm: "loans.apply", render: applyView },
  { path: "/repayments", title: "Repayments", section: "Borrowing", icon: "repay", perm: "repayments.make", render: repaymentsView },
  { path: "/trust", title: "Trust score", section: "Borrowing", icon: "trust", perm: "trust.view_own", render: trustView },

  // Investing
  { path: "/marketplace", title: "Loan marketplace", section: "Investing", icon: "market", perm: "marketplace.view", render: marketplaceView },
  { path: "/portfolio", title: "Portfolio", section: "Investing", icon: "portfolio", perm: "investments.view_own", render: portfolioView },

  // Guarantees
  { path: "/guarantees", title: "Guarantees", section: "Guarantees", icon: "shield", perm: "guarantees.view_own", render: guaranteesView },
  { path: "/commissions", title: "Commissions", section: "Guarantees", icon: "commission", perm: "commissions.view_own", render: commissionsView },

  // Money
  { path: "/wallet", title: "Wallet", section: "Money", icon: "wallet", perm: "wallet.view_own", render: walletView },
  { path: "/statements", title: "Statements", section: "Money", icon: "statement", perm: "statements.view_own", render: statementsView },

  // Administration
  { path: "/admin/integrations", title: "Payments & SMS", section: "Administration", icon: "wallet", perm: "admin.config.manage", render: adminIntegrationsView },
  { path: "/admin/terms", title: "Terms & conditions", section: "Administration", icon: "statement", perm: "admin.config.manage", render: adminTermsView },
  { path: "/admin/users", title: "Users", section: "Administration", icon: "users", perm: "admin.users.view", render: usersView },
  { path: "/admin/kyc", title: "KYC review", section: "Administration", icon: "review", perm: "admin.kyc.view", render: adminKycListView },
  { path: "/admin/kyc/:id", title: "KYC submission", hidden: true, parent: "/admin/kyc", perm: "admin.kyc.view", render: adminKycDetailView },
  { path: "/admin/loans", title: "Loans", section: "Administration", icon: "loan", perm: "admin.loans.view", render: adminLoanListView },
  { path: "/admin/loans/:id", title: "Loan", hidden: true, parent: "/admin/loans", perm: "admin.loans.view", render: adminLoanDetailView },
  { path: "/admin/extensions", title: "Extensions", section: "Administration", icon: "repay", perm: "admin.extensions.review", render: adminExtensionsView },
  { path: "/admin/defaults", title: "Arrears & defaults", section: "Administration", icon: "alert", perm: "admin.defaults.manage", render: adminDefaultsView },
  { path: "/admin/withdrawals", title: "Withdrawals", section: "Administration", icon: "withdraw", perm: "admin.withdrawals.approve", render: adminWithdrawalsView },
  { path: "/admin/finance", title: "Ledger & wallets", section: "Administration", icon: "ledger",
    perm: ["admin.ledger.view", "admin.wallets.view", "admin.reconciliation.run", "admin.revenue.view"], render: adminFinanceView },
  { path: "/admin/reports", title: "Reports", section: "Administration", icon: "report", perm: "admin.reports.view", render: adminReportsView },
  { path: "/admin/disputes", title: "Disputes", section: "Administration", icon: "flag", perm: "admin.disputes.view", render: adminDisputesView },
  { path: "/admin/moderation", title: "Reports & support", section: "Administration", icon: "chat", perm: ["admin.moderation.view", "admin.support.chat"], render: adminModerationView },
  { path: "/admin/config", title: "Configuration", section: "Administration", icon: "settings", perm: "admin.config.manage", render: adminConfigView },
  { path: "/admin/audit", title: "Audit trail", section: "Administration", icon: "audit", perm: "admin.audit.view", render: auditView },

  // Account
  { path: "/notifications", title: "Notifications", section: "Account", icon: "bell", perm: "notifications.view", render: notificationsView, badge: "notifications" },
  { path: "/disputes", title: "Disputes", section: "Account", icon: "flag", perm: "disputes.raise", render: disputesView },
  { path: "/kyc", title: "Identity verification", section: "Account", icon: "id", perm: "kyc.submit", render: kycView },
  { path: "/profile", title: "Profile", section: "Account", icon: "user", perm: "profile.view", render: profileView },
];

/** Match a path like "/loans/123" against the table. Returns { route, params } or null. */
export function findRoute(path) {
  for (const route of ROUTES) {
    const names = [];
    const pattern = new RegExp(
      "^" + route.path.replace(/:([a-z]+)/g, (_, name) => { names.push(name); return "([^/]+)"; }) + "$"
    );
    const m = path.match(pattern);
    if (m) {
      const params = {};
      names.forEach((n, i) => { params[n] = decodeURIComponent(m[i + 1]); });
      return { route, params };
    }
  }
  return null;
}
