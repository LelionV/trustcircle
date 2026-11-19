"""URLs for Phases 5-10: wallet, payments, investing, offers, guarantees, repayments,
extensions, notifications, chat, disputes, finance and reports."""
from django.urls import path

from apps.administration import disputes
from apps.chat import views as chat
from apps.guarantors import views as guarantees
from apps.investments import views as investments
from apps.loans import lifecycle_views as lifecycle
from apps.notifications import views as notifications
from apps.payments import views as payments
from apps.repayments import views as repayments
from apps.reports import views as reports

urlpatterns = [
    # Card and checkout providers call these back (IntaSend, Pesapal, Paystack)
    path("payments/webhooks/<str:provider>/", payments.GatewayWebhookView.as_view(), name="payments-webhook"),
    # Wallet and payments
    path("wallet/", payments.WalletView.as_view(), name="wallet"),
    path("wallet/transactions/", payments.TransactionsView.as_view(), name="wallet-transactions"),
    path("wallet/statement.csv", payments.StatementCsvView.as_view(), name="wallet-statement"),
    path("wallet/fees/quote/", payments.FeeQuoteView.as_view(), name="wallet-fee-quote"),
    path("wallet/deposit/", payments.DepositView.as_view(), name="wallet-deposit"),
    path("wallet/withdraw/", payments.WithdrawView.as_view(), name="wallet-withdraw"),
    path("wallet/transfer/", payments.TransferView.as_view(), name="wallet-transfer"),
    path("payments/", payments.PaymentsView.as_view(), name="payments"),
    path("payments/<uuid:pk>/", payments.PaymentDetailView.as_view(), name="payment"),
    path("payments/<uuid:pk>/cancel/", payments.PaymentCancelView.as_view(), name="payment-cancel"),
    path("payments/<uuid:pk>/sandbox-confirm/", payments.SandboxConfirmView.as_view(), name="payment-sandbox"),
    path("payments/mpesa/callback/", payments.MpesaStkCallbackView.as_view(), name="mpesa-callback"),
    path("payments/mpesa/b2c-result/", payments.MpesaB2cResultView.as_view(), name="mpesa-b2c-result"),
    path("payments/mpesa/b2c-timeout/", payments.MpesaB2cTimeoutView.as_view(), name="mpesa-b2c-timeout"),
    # Investing and offers
    path("marketplace/<uuid:pk>/invest/", investments.InvestView.as_view(), name="invest"),
    path("marketplace/<uuid:pk>/offers/", investments.OfferView.as_view(), name="make-offer"),
    path("offers/", investments.MyOffersView.as_view(), name="my-offers"),
    path("offers/<uuid:offer_id>/", investments.MyOfferView.as_view(), name="my-offer"),
    path("portfolio/", investments.PortfolioView.as_view(), name="portfolio"),
    path("investments/", investments.MyInvestmentsView.as_view(), name="my-investments"),
    path("investments/statement.csv", investments.InvestorStatementView.as_view(), name="investor-statement"),
    path("investments/<uuid:pk>/withdraw/", investments.InvestmentWithdrawView.as_view(), name="investment-withdraw"),
    path("investments/<uuid:pk>/distributions/", investments.InvestmentDistributionsView.as_view(),
         name="investment-distributions"),
    path("extensions/<uuid:ext_id>/vote/", investments.ExtensionVoteView.as_view(), name="extension-vote"),
    # Guarantees
    path("guarantees/", guarantees.MyGuaranteesView.as_view(), name="my-guarantees"),
    path("guarantees/<uuid:pk>/respond/", guarantees.GuaranteeRespondView.as_view(), name="guarantee-respond"),
    path("guarantees/<uuid:pk>/withdraw/", guarantees.GuaranteeWithdrawView.as_view(), name="guarantee-withdraw"),
    path("guarantees/<uuid:pk>/pay-claim/", guarantees.GuaranteeClaimPayView.as_view(), name="guarantee-pay-claim"),
    # The borrower's loan after approval
    path("loans/<uuid:pk>/agreement/", lifecycle.AgreementView.as_view(), name="loan-agreement"),
    path("loans/<uuid:pk>/guarantor/", lifecycle.RenominateGuarantorView.as_view(), name="loan-guarantor"),
    path("loans/<uuid:pk>/offers/<uuid:offer_id>/", lifecycle.OfferDecisionView.as_view(), name="loan-offer"),
    path("loans/<uuid:pk>/repay/", lifecycle.RepayView.as_view(), name="loan-repay"),
    path("loans/<uuid:pk>/extension/", lifecycle.ExtensionView.as_view(), name="loan-extension"),
    path("loans/<uuid:pk>/extension/<uuid:ext_id>/cancel/", lifecycle.ExtensionCancelView.as_view(),
         name="loan-extension-cancel"),
    path("repayments/", lifecycle.MyRepaymentsView.as_view(), name="my-repayments"),
    # Notifications
    path("notifications/", notifications.NotificationsView.as_view(), name="notifications"),
    path("notifications/unread/", notifications.UnreadCountView.as_view(), name="notifications-unread"),
    path("notifications/read/", notifications.MarkReadView.as_view(), name="notifications-read"),
    path("notifications/devices/", notifications.DeviceView.as_view(), name="notifications-devices"),
    # Chat and reports
    path("chat/", chat.ConversationsView.as_view(), name="chat"),
    path("chat/<uuid:pk>/", chat.ConversationView.as_view(), name="chat-conversation"),
    path("chat/<uuid:pk>/block/", chat.BlockView.as_view(), name="chat-block"),
    path("reports/users/", chat.ReportView.as_view(), name="report-user"),
    # Disputes
    path("disputes/", disputes.MyDisputesView.as_view(), name="my-disputes"),
    # Staff
    path("admin/payments/", payments.AdminPaymentsView.as_view(), name="admin-payments"),
    path("admin/payments/<uuid:pk>/decision/", payments.AdminWithdrawalDecisionView.as_view(),
         name="admin-withdrawal-decision"),
    path("admin/users/<uuid:pk>/wallet/", payments.AdminWalletView.as_view(), name="admin-user-wallet"),
    path("admin/loans/<uuid:pk>/disburse/", lifecycle.AdminDisburseView.as_view(), name="admin-loan-disburse"),
    path("admin/loans/<uuid:pk>/cancel-funding/", lifecycle.AdminCancelFundingView.as_view(),
         name="admin-loan-cancel-funding"),
    path("admin/loans/<uuid:pk>/default/", repayments.AdminMarkDefaultView.as_view(), name="admin-loan-default"),
    path("admin/extensions/", repayments.AdminExtensionsView.as_view(), name="admin-extensions"),
    path("admin/extensions/<uuid:pk>/decision/", repayments.AdminExtensionDecisionView.as_view(),
         name="admin-extension-decision"),
    path("admin/defaults/", repayments.AdminDefaultsView.as_view(), name="admin-defaults"),
    path("admin/claims/<int:pk>/", repayments.AdminClaimView.as_view(), name="admin-claim"),
    path("admin/finance/reconcile/", reports.ReconcileView.as_view(), name="admin-reconcile"),
    path("admin/finance/revenue/", reports.RevenueView.as_view(), name="admin-revenue"),
    path("admin/finance/ledger/", reports.LedgerEntriesView.as_view(), name="admin-ledger"),
    path("admin/reports/", reports.MetricsView.as_view(), name="admin-reports"),
    path("admin/reports/<str:name>.csv", reports.ExportView.as_view(), name="admin-report-export"),
    path("admin/config/platform/", reports.PlatformRulesView.as_view(), name="admin-config-platform"),
    path("admin/jobs/run/", reports.RunJobsView.as_view(), name="admin-jobs-run"),
    path("admin/disputes/", disputes.AdminDisputesView.as_view(), name="admin-disputes"),
    path("admin/disputes/<uuid:pk>/", disputes.AdminDisputeView.as_view(), name="admin-dispute"),
    path("admin/moderation/reports/", chat.AdminReportsView.as_view(), name="admin-moderation-reports"),
    path("admin/moderation/reports/<uuid:pk>/", chat.AdminReportDetailView.as_view(),
         name="admin-moderation-report"),
    path("admin/support/chats/", chat.AdminSupportChatsView.as_view(), name="admin-support-chats"),
]
