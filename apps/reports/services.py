"""
Financial and operational reports. Every figure is computed from the
ledger, the loans and the investments; nothing is estimated.
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounting import services as ledger
from apps.common.dates import date_range_filter
from apps.common.money import ZERO


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


def portfolio_metrics(today=None):
    from apps.investments.models import Investment
    from apps.loans.models import Loan, LoanInstallment, PAID_STATUSES
    from apps.repayments.models import Repayment

    today = today or timezone.localdate()
    live = Loan.objects.filter(status__in=["ACTIVE", "OVERDUE", "DEFAULTED"])
    disbursed = Loan.objects.filter(disbursed_at__isnull=False)
    unpaid = LoanInstallment.objects.filter(loan__in=live).exclude(status__in=PAID_STATUSES)
    outstanding_principal = sum((i.principal - i.principal_paid for i in unpaid.only("principal", "principal_paid")),
                                ZERO)

    def par(days):
        """Portfolio at risk: outstanding principal of loans with a payment more than `days` late."""
        late_loans = unpaid.filter(due_date__lt=today - timedelta(days=days)).values_list("loan_id", flat=True)
        rows = unpaid.filter(loan_id__in=set(late_loans)).only("principal", "principal_paid")
        return sum((i.principal - i.principal_paid for i in rows), ZERO)

    par30 = par(30)
    finished = Loan.objects.filter(status__in=["COMPLETED", "DEFAULTED"])
    defaulted = finished.filter(status="DEFAULTED").count()
    return {
        "as_of": today,
        "loans_by_status": dict(Loan.objects.order_by().values_list("status").annotate(n=Count("pk"))),
        "total_disbursed": _sum(disbursed, "amount"),
        "loans_disbursed": disbursed.count(),
        "outstanding_principal": outstanding_principal,
        "par_1": par(0),
        "par_30": par30,
        "par_30_percent": (par30 * 100 / outstanding_principal).quantize(Decimal("0.01"))
        if outstanding_principal else ZERO,
        "default_rate_percent": (Decimal(defaulted) * 100 / finished.count()).quantize(Decimal("0.01"))
        if finished.count() else ZERO,
        "repaid_total": _sum(Repayment.objects.all(), "amount"),
        "repaid_principal": _sum(Repayment.objects.all(), "principal"),
        "repaid_interest": _sum(Repayment.objects.all(), "interest"),
        "investors_with_money_lent": Investment.objects.filter(status__in=["ACTIVE", "DEFAULTED"])
        .values("investor").distinct().count(),
        "open_for_funding": Loan.objects.filter(status__in=["PUBLISHED", "PARTIALLY_FUNDED"]).count(),
        "funding_needed": sum((l.amount - l.funded_amount for l in
                               Loan.objects.filter(status__in=["PUBLISHED", "PARTIALLY_FUNDED"])), ZERO),
    }


def finance_summary(start=None, end=None):
    from apps.payments.models import Direction, IntentStatus, PaymentIntent

    intents = PaymentIntent.objects.filter(status=IntentStatus.SUCCEEDED)
    intents = intents.filter(**date_range_filter("created_at", start, end))
    revenue = ledger.revenue_by_category(start, end)
    return {
        "period": {"start": start, "end": end},
        "deposits": _sum(intents.filter(direction=Direction.IN), "amount"),
        "deposit_count": intents.filter(direction=Direction.IN).count(),
        "withdrawals": _sum(intents.filter(direction=Direction.OUT), "amount"),
        "withdrawal_count": intents.filter(direction=Direction.OUT).count(),
        "withdrawals_awaiting_approval": PaymentIntent.objects.filter(status=IntentStatus.AWAITING_APPROVAL).count(),
        "revenue": revenue,
        "revenue_total": sum((r["amount"] for r in revenue.values()), ZERO),
    }


def _csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def loans_csv():
    from apps.loans.models import Loan

    return _csv(
        ["reference", "borrower", "status", "amount", "annual_rate", "funded", "disbursed_at", "completed_at",
         "defaulted_at", "extensions"],
        ([l.reference, l.borrower.email, l.status, l.amount, l.annual_rate, l.funded_amount,
          l.disbursed_at and l.disbursed_at.date(), l.completed_at and l.completed_at.date(),
          l.defaulted_at and l.defaulted_at.date(), l.extension_count]
         for l in Loan.objects.select_related("borrower").order_by("created_at")))


def repayments_csv(start=None, end=None):
    from apps.repayments.models import Repayment

    qs = Repayment.objects.select_related("loan", "payer").order_by("created_at")
    qs = qs.filter(**date_range_filter("created_at", start, end))
    return _csv(["date", "loan", "payer", "amount", "principal", "interest", "extension_interest", "extension_fee",
                 "late_fee", "entry"],
                ([r.created_at.date(), r.loan.reference, r.payer.email, r.amount, r.principal, r.interest,
                  r.extension_interest, r.extension_fee, r.late_fee, r.entry.reference] for r in qs))


def ledger_csv(start=None, end=None):
    from apps.accounting.models import LedgerLine

    qs = LedgerLine.objects.select_related("entry", "account", "account__owner").order_by("entry__created_at", "id")
    qs = qs.filter(**date_range_filter("entry__created_at", start, end))
    return _csv(["date", "entry", "kind", "account_owner", "account", "side", "amount", "memo", "description"],
                ([l.entry.created_at.isoformat(), l.entry.reference, l.entry.kind,
                  l.account.owner.email if l.account.owner_id else "PLATFORM", l.account.kind, l.side, l.amount,
                  l.memo, l.entry.description] for l in qs))


def revenue_csv(start=None, end=None):
    rev = ledger.revenue_by_category(start, end)
    return _csv(["category", "label", "amount"], ([k, v["label"], v["amount"]] for k, v in rev.items()))


def statement_csv(user, start=None, end=None):
    """A customer's wallet statement: every ledger line on their accounts."""
    qs = ledger.user_lines(user)
    qs = qs.filter(**date_range_filter("entry__created_at", start, end))
    rows = []
    for l in qs.order_by("entry__created_at", "id"):
        signed = l.amount if l.side == "CREDIT" else -l.amount
        rows.append([timezone.localtime(l.entry.created_at).strftime("%Y-%m-%d %H:%M"), l.entry.reference,
                     l.entry.get_kind_display(), l.account.get_kind_display(), l.memo or l.entry.description,
                     signed, l.balance_after])
    return _csv(["date", "reference", "type", "balance", "details", "amount", "balance_after"], rows)


EXPORTS = {
    "loans": ("Loans", loans_csv),
    "repayments": ("Repayments", repayments_csv),
    "ledger": ("Ledger lines", ledger_csv),
    "revenue": ("Revenue by category", revenue_csv),
}


def parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
