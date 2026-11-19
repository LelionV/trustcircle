"""
Scheduled jobs. Run them every day (and every hour for funding expiry and
consent windows); each one is safe to run repeatedly.

    python manage.py run_scheduled_jobs            # all jobs
    python manage.py run_scheduled_jobs overdue    # one job

or with Celery beat (see config/celery.py).
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

log = logging.getLogger(__name__)


def expire_funding():
    from apps.investments.services import expire_funding_rounds

    return {"cancelled": expire_funding_rounds()}


def overdue():
    from apps.repayments.services import process_overdue

    return process_overdue()


def claims():
    from apps.repayments.services import collect_open_claims

    return {"claims_collected": collect_open_claims()}


def consent():
    from apps.repayments.services import close_consent_windows

    return {"extensions_decided": close_consent_windows()}


def account_fees():
    """Monthly account fee (if configured above zero). Charged once per user per month, never into debt."""
    from apps.accounting import services as ledger
    from apps.accounting.models import AccountKind, EntryKind, JournalEntry
    from apps.accounts.models import Role, User
    from apps.commissions.services import rules
    from apps.notifications.services import notify

    fee = Decimal(rules()["fees"]["account_management_monthly"])
    if fee <= 0:
        return {"charged": 0}
    month = timezone.localdate().strftime("%Y%m")
    charged = 0
    for user in User.objects.filter(is_active=True).exclude(role=Role.ADMIN):
        key = f"acctfee-{user.pk}-{month}"
        if JournalEntry.objects.filter(idempotency_key=key).exists() or ledger.balances(user)["available"] < fee:
            continue
        with transaction.atomic():
            ledger.post(
                EntryKind.FEE, f"Account fee {month}",
                [ledger.Line(ledger.wallet(user), "DEBIT", fee, "Monthly account fee"),
                 ledger.Line(ledger.platform(AccountKind.REVENUE_ACCOUNT_FEE), "CREDIT", fee, "Account fee")],
                idempotency_key=key)
            charged += 1
            notify(user, "account_fee", "Monthly account fee",
                   f"KES {fee:,.2f} account fee for {month[:4]}-{month[4:]}.", "#/wallet",
                   dedupe_key=f"acctfee-{month}")
    return {"charged": charged}


def reconcile():
    from apps.accounting.services import reconcile as run
    from apps.notifications.services import notify_admins

    result = run()
    if not result["ok"]:
        log.error("Reconciliation found %s problem(s)", len(result["problems"]))
        notify_admins("admin.reconciliation.run", "reconciliation_failed", "Reconciliation found problems",
                      f"{len(result['problems'])} problem(s). Open Finance → Reconciliation.", "#/admin/finance")
    return {"ok": result["ok"], "problems": len(result["problems"])}


JOBS = {
    "expire_funding": expire_funding,
    "overdue": overdue,
    "claims": claims,
    "consent": consent,
    "account_fees": account_fees,
    "reconcile": reconcile,
}


def run(names=None):
    results = {}
    for name in names or JOBS:
        try:
            results[name] = JOBS[name]()
        except Exception as exc:  # noqa: BLE001 - one failing job mustn't stop the others
            log.exception("Scheduled job %s failed", name)
            results[name] = {"error": str(exc)}
    return results
