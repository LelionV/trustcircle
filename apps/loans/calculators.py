"""
Interest brackets and repayment schedules: pure functions, Decimal only.

Interest methods
  FLAT              interest is worked out on the original amount for the
                    whole term, then spread evenly over the installments.
  REDUCING_BALANCE  equal installments; each period's interest is charged
                    only on what is still owed (standard amortisation).

Rate basis (how the bracket rate is read)
  ANNUAL    % per year (default)
  MONTHLY   % per month
  PER_LOAN  % of the amount, once, for the whole loan (always flat)

Rounding: every installment is rounded to the cent and the final installment
absorbs the remainder, so principal parts always add up to the amount
borrowed exactly.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
PERIODS_PER_YEAR = {"WEEKLY": 52, "BIWEEKLY": 26, "MONTHLY": 12}
FREQUENCY_LABELS = {"WEEKLY": "Weekly", "BIWEEKLY": "Every two weeks", "MONTHLY": "Monthly"}


class ScheduleError(ValueError):
    pass


class BracketError(ValueError):
    pass


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


# --- Interest brackets ----------------------------------------------------------

def validate_brackets(rows) -> list[dict]:
    """
    rows: [{"min_score", "max_score", "label", "annual_rate" (None = manual review)}]
    Must cover 0–100 with no gaps or overlaps.
    """
    if not rows:
        raise BracketError("Add at least one bracket.")
    cleaned = []
    try:
        for r in rows:
            rate = r.get("annual_rate")
            rate = None if rate in (None, "") else Decimal(str(rate))
            label = str(r.get("label", "")).strip()
            if not label:
                raise BracketError("Every bracket needs a name.")
            if rate is not None and not (Decimal("0") <= rate <= Decimal("100")):
                raise BracketError(f"The rate for '{label}' must be between 0 and 100%.")
            cleaned.append({"min_score": int(r["min_score"]), "max_score": int(r["max_score"]),
                            "label": label[:40], "annual_rate": None if rate is None else rate.quantize(CENT)})
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        if isinstance(exc, BracketError):
            raise
        raise BracketError("Each bracket needs a lowest score, highest score, name and rate.") from exc
    cleaned.sort(key=lambda r: r["min_score"])
    expected = 0
    for r in cleaned:
        if r["min_score"] != expected:
            raise BracketError(
                (f"Score {expected} isn't covered." if r["min_score"] - 1 == expected
                 else f"Scores {expected}–{r['min_score'] - 1} aren't covered.") if r["min_score"] > expected
                else f"Brackets overlap at score {r['min_score']}.")
        if r["max_score"] < r["min_score"]:
            raise BracketError(f"'{r['label']}' ends before it starts.")
        expected = r["max_score"] + 1
    if expected != 101:
        raise BracketError("The highest bracket must end at 100." if expected <= 100 else "Scores stop at 100.")
    return cleaned


def find_bracket(rows, score):
    for r in rows:
        if r["min_score"] <= score <= r["max_score"]:
            return r
    return None


def next_better_bracket(rows, score):
    """The next bracket above the current one that has a lower rate, if any."""
    current = find_bracket(rows, score)
    current_rate = current["annual_rate"] if current else None
    for r in sorted(rows, key=lambda r: r["min_score"]):
        if r["min_score"] <= score or r["annual_rate"] is None:
            continue
        if current_rate is None or r["annual_rate"] < current_rate:
            return {**r, "points_needed": r["min_score"] - score}
    return None


# --- Schedules ---------------------------------------------------------------------

def installment_count(term_months: int, frequency: str) -> int:
    if frequency not in PERIODS_PER_YEAR:
        raise ScheduleError("Unknown repayment frequency.")
    if term_months < 1:
        raise ScheduleError("The repayment period must be at least one month.")
    if frequency == "MONTHLY":
        return term_months
    n = (Decimal(term_months) * PERIODS_PER_YEAR[frequency] / 12).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(1, int(n))


def due_date(start: date, frequency: str, k: int) -> date:
    """Date of installment k (1-based)."""
    if frequency == "WEEKLY":
        return start + timedelta(days=7 * k)
    if frequency == "BIWEEKLY":
        return start + timedelta(days=14 * k)
    month_index = start.month - 1 + k
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def total_flat_interest(principal: Decimal, rate: Decimal, basis: str, term_months: int) -> Decimal:
    if basis == "ANNUAL":
        return money(principal * rate / 100 * term_months / 12)
    if basis == "MONTHLY":
        return money(principal * rate / 100 * term_months)
    if basis == "PER_LOAN":
        return money(principal * rate / 100)
    raise ScheduleError("Unknown rate basis.")


def periodic_rate(rate: Decimal, basis: str, frequency: str) -> Decimal:
    per_year = PERIODS_PER_YEAR[frequency]
    if basis == "ANNUAL":
        return rate / 100 / per_year
    if basis == "MONTHLY":
        return rate / 100 * 12 / per_year
    raise ScheduleError("Reducing-balance loans need an annual or monthly rate.")


def _even_split(total: Decimal, n: int) -> list[Decimal]:
    base = (total / n).quantize(CENT, rounding=ROUND_DOWN)
    return [base] * (n - 1) + [total - base * (n - 1)]


def build_schedule(*, principal, annual_rate, method, basis, frequency, term_months, start_date) -> dict:
    principal = money(principal)
    rate = Decimal(str(annual_rate))
    if principal <= 0:
        raise ScheduleError("The amount must be more than zero.")
    if rate < 0:
        raise ScheduleError("The interest rate can't be negative.")
    n = installment_count(term_months, frequency)
    effective_method = "FLAT" if basis == "PER_LOAN" else method

    rows = []
    if effective_method == "FLAT":
        interest_total = total_flat_interest(principal, rate, basis, term_months)
        principal_parts = _even_split(principal, n)
        interest_parts = _even_split(interest_total, n)
        balance = principal
        for k in range(n):
            balance -= principal_parts[k]
            rows.append((principal_parts[k], interest_parts[k], balance))
    elif effective_method == "REDUCING_BALANCE":
        r = periodic_rate(rate, basis, frequency)
        payment = money(principal / n) if r == 0 else money(principal * r / (1 - (1 + r) ** -n))
        balance = principal
        for k in range(n):
            interest = money(balance * r)
            part = balance if k == n - 1 else min(balance, payment - interest)
            balance -= part
            rows.append((part, interest, balance))
    else:
        raise ScheduleError("Unknown interest method.")

    installments = []
    for k, (part, interest, balance) in enumerate(rows, start=1):
        installments.append({
            "sequence": k,
            "due_date": due_date(start_date, frequency, k),
            "principal": part,
            "interest": interest,
            "fees": Decimal("0.00"),
            "total": part + interest,
            "balance_after": balance,
        })
    total_interest = sum((i["interest"] for i in installments), Decimal("0.00"))
    largest = max(i["total"] for i in installments)
    return {
        "principal": principal,
        "annual_rate": rate.quantize(CENT),
        "method": effective_method,
        "basis": basis,
        "frequency": frequency,
        "term_months": term_months,
        "installment_count": n,
        "installments": installments,
        "total_interest": total_interest,
        "total_repayable": principal + total_interest,
        "first_installment": installments[0]["total"],
        "largest_installment": largest,
        # What the largest installment amounts to per month, for affordability checks.
        "monthly_equivalent": money(largest * PERIODS_PER_YEAR[frequency] / 12),
        "first_due_date": installments[0]["due_date"],
        "final_due_date": installments[-1]["due_date"],
    }
