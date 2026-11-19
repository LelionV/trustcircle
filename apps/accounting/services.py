"""
Posting to the ledger. The only way money moves on the platform.

    post(kind, description, lines=[Line(account, "DEBIT"/"CREDIT", amount, memo), ...])

* debits must equal credits, amounts must be positive
* accounts are locked in a fixed order (by id) to avoid deadlocks
* user wallet accounts can never go below zero
* an idempotency key makes a retried call return the original entry
"""
import secrets
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.common.exceptions import BusinessRuleViolation
from apps.common.dates import date_range_filter
from apps.common.money import ZERO, quantize_money

from .models import (
    DEBIT_NORMAL,
    REVENUE_KINDS,
    USER_KINDS,
    AccountKind,
    EntryKind,
    JournalEntry,
    LedgerAccount,
    LedgerLine,
)


class InsufficientFunds(BusinessRuleViolation):
    default_code = "insufficient_funds"
    default_detail = "There isn't enough money in the wallet for this."


@dataclass
class Line:
    account: LedgerAccount
    side: str  # "DEBIT" or "CREDIT"
    amount: Decimal
    memo: str = ""


def account(owner, kind):
    """Get or create the ledger account for a user (or the platform when owner is None)."""
    acc = LedgerAccount.objects.filter(owner=owner, kind=kind, currency="KES").first()
    if acc is None:
        try:
            with transaction.atomic():
                acc = LedgerAccount.objects.create(owner=owner, kind=kind, currency="KES")
        except IntegrityError:
            acc = LedgerAccount.objects.get(owner=owner, kind=kind, currency="KES")
    return acc


def wallet(user, kind=AccountKind.WALLET_AVAILABLE):
    return account(user, kind)


def platform(kind):
    return account(None, kind)


def _reference(prefix="JE"):
    while True:
        ref = f"{prefix}-{timezone.localdate():%y%m%d}-{secrets.token_hex(4).upper()}"
        if not JournalEntry.objects.filter(reference=ref).exists():
            return ref


def _delta(acc, side, amount):
    """How a line changes the account's balance in its normal direction."""
    increases = (side == "DEBIT") if acc.kind in DEBIT_NORMAL else (side == "CREDIT")
    return amount if increases else -amount


@transaction.atomic
def post(kind, description, lines, *, loan=None, external_reference="", idempotency_key=None,
         initiated_by=None, reverses=None, allow_negative=False):
    if idempotency_key:
        existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    lines = [l for l in lines if quantize_money(l.amount) != ZERO]
    if not lines:
        raise BusinessRuleViolation("Nothing to post.", code="empty_entry")
    debits = sum((quantize_money(l.amount) for l in lines if l.side == "DEBIT"), ZERO)
    credits = sum((quantize_money(l.amount) for l in lines if l.side == "CREDIT"), ZERO)
    if debits != credits:
        raise ValueError(f"Unbalanced entry: debits {debits} != credits {credits}")
    if any(quantize_money(l.amount) < 0 for l in lines):
        raise ValueError("Ledger amounts must be positive.")

    ids = sorted({l.account.pk for l in lines})
    locked = {a.pk: a for a in LedgerAccount.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    entry = JournalEntry.objects.create(
        reference=_reference("RV" if reverses else "JE"), kind=kind, description=description[:255], loan=loan,
        external_reference=external_reference, idempotency_key=idempotency_key, initiated_by=initiated_by,
        reverses=reverses,
    )
    for l in lines:
        acc = locked[l.account.pk]
        amount = quantize_money(l.amount)
        acc.balance = quantize_money(acc.balance + _delta(acc, l.side, amount))
        if acc.kind in USER_KINDS and acc.balance < 0 and not allow_negative:
            raise InsufficientFunds(
                f"Not enough money: this needs KES {amount:,.2f} from the {acc.get_kind_display().lower()} balance.")
        acc.save(update_fields=["balance"])
        LedgerLine.objects.create(entry=entry, account=acc, side=l.side, amount=amount, currency=acc.currency,
                                  memo=l.memo[:160], balance_after=acc.balance)
    return entry


@transaction.atomic
def reverse(entry, *, actor, reason):
    """Post the mirror image of an entry. The original stays, linked to its reversal."""
    if hasattr(entry, "reversed_by"):
        raise BusinessRuleViolation("This entry has already been reversed.", code="already_reversed")
    lines = [Line(l.account, "CREDIT" if l.side == "DEBIT" else "DEBIT", l.amount, f"Reversal: {l.memo}")
             for l in entry.lines.select_related("account")]
    return post(EntryKind.REVERSAL, f"Reversal of {entry.reference}: {reason}", lines, loan=entry.loan,
                initiated_by=actor, reverses=entry, allow_negative=False)


def balances(user):
    """The four wallet balances for a user."""
    rows = dict(LedgerAccount.objects.filter(owner=user, kind__in=USER_KINDS).values_list("kind", "balance"))
    return {
        "available": rows.get(AccountKind.WALLET_AVAILABLE, ZERO),
        "pending": rows.get(AccountKind.WALLET_PENDING, ZERO),
        "invested": rows.get(AccountKind.WALLET_ESCROW, ZERO),
        "held": rows.get(AccountKind.WALLET_FROZEN, ZERO),
        "locked": rows.get(AccountKind.WALLET_GUARANTEE_LOCK, ZERO),
    }


def revenue_by_category(start=None, end=None):
    qs = LedgerLine.objects.filter(account__kind__in=REVENUE_KINDS, account__owner__isnull=True)
    qs = qs.filter(**date_range_filter("entry__created_at", start, end))
    result = {}
    for kind in sorted(REVENUE_KINDS):
        credit = qs.filter(account__kind=kind, side="CREDIT").aggregate(t=Sum("amount"))["t"] or ZERO
        debit = qs.filter(account__kind=kind, side="DEBIT").aggregate(t=Sum("amount"))["t"] or ZERO
        result[kind] = {"label": AccountKind(kind).label, "amount": credit - debit}
    return result


def reconcile():
    """
    Integrity checks, all of which should pass:
      1. every journal entry balances
      2. every account's cached balance equals the sum of its lines
      3. money held (clearing) equals money owed to users plus revenue
    """
    problems = []
    for entry in JournalEntry.objects.prefetch_related("lines"):
        d = sum((l.amount for l in entry.lines.all() if l.side == "DEBIT"), ZERO)
        c = sum((l.amount for l in entry.lines.all() if l.side == "CREDIT"), ZERO)
        if d != c:
            problems.append({"check": "balanced_entries", "detail": f"{entry.reference}: debits {d} vs credits {c}"})
    accounts = list(LedgerAccount.objects.select_related("owner"))
    debit_total = credit_total = ZERO
    for acc in accounts:
        d = acc.lines.filter(side="DEBIT").aggregate(t=Sum("amount"))["t"] or ZERO
        c = acc.lines.filter(side="CREDIT").aggregate(t=Sum("amount"))["t"] or ZERO
        derived = (d - c) if acc.kind in DEBIT_NORMAL else (c - d)
        if derived != acc.balance:
            problems.append({"check": "cached_balances", "detail": f"{acc}: cached {acc.balance} vs lines {derived}"})
        if acc.kind in DEBIT_NORMAL:
            debit_total += derived
        else:
            credit_total += derived
    if debit_total != credit_total:
        problems.append({"check": "books_balance",
                         "detail": f"Money held {debit_total} vs owed to users + revenue {credit_total}"})
    return {
        "ok": not problems,
        "checked_at": timezone.now(),
        "entries": JournalEntry.objects.count(),
        "accounts": len(accounts),
        "money_held": debit_total,
        "owed_and_revenue": credit_total,
        "owed_to_users": sum((a.balance for a in accounts if a.kind in USER_KINDS), ZERO),
        "revenue": sum((a.balance for a in accounts if a.kind in REVENUE_KINDS), ZERO),
        "problems": problems,
    }


def user_lines(user):
    return (LedgerLine.objects.filter(account__owner=user)
            .select_related("entry", "account").order_by("-entry__created_at", "-id"))


__all__ = ["Line", "InsufficientFunds", "account", "wallet", "platform", "post", "reverse", "balances",
           "revenue_by_category", "reconcile", "user_lines", "Q"]
