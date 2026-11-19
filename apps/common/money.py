"""
Money primitives shared by every financial module.

Rules:
* Monetary values are always ``decimal.Decimal`` — never ``float``.
* Amounts are stored with 2 decimal places (KES cents) and rounded
  ROUND_HALF_UP only at well-defined points.
* When a total is split between several parties, the parts must add up to
  the total exactly. ``allocate`` guarantees that.
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation


def _decimal_places() -> int:
    """Settings value when Django is configured; 2 otherwise (pure calculators, scripts)."""
    try:
        from django.conf import settings

        return getattr(settings, "MONEY_DECIMAL_PLACES", 2)
    except Exception:  # noqa: BLE001 - Django missing or not configured
        return 2

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class MoneyError(ValueError):
    """Raised for invalid monetary input."""


def to_decimal(value: Decimal | int | str) -> Decimal:
    """Convert to Decimal, rejecting floats (they carry binary rounding error)."""
    if isinstance(value, bool):
        raise MoneyError("Booleans are not valid monetary amounts.")
    if isinstance(value, float):
        raise MoneyError("Floats are not allowed for money; pass a str or Decimal.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"Invalid monetary amount: {value!r}") from exc
    if not result.is_finite():
        raise MoneyError(f"Monetary amount must be finite: {value!r}")
    return result


def quantize_money(value: Decimal | int | str, rounding: str = ROUND_HALF_UP) -> Decimal:
    """Round to the platform's currency precision (2 dp for KES)."""
    places = Decimal(1).scaleb(-_decimal_places())
    return to_decimal(value).quantize(places, rounding=rounding)


def percentage_of(amount: Decimal | int | str, percent: Decimal | int | str) -> Decimal:
    """``percent`` % of ``amount``, rounded to cents (e.g. 3% of 6000 -> 180.00)."""
    return quantize_money(to_decimal(amount) * to_decimal(percent) / Decimal(100))


def allocate(total: Decimal | int | str, weights: Sequence[Decimal | int | str]) -> list[Decimal]:
    """
    Split ``total`` into parts proportional to ``weights``.

    Uses the largest-remainder method so the parts always sum exactly to
    ``total`` (no cent is created or lost). Ties for the leftover cents are
    broken by input order, which makes the result deterministic.

    >>> allocate("100.00", [1, 1, 1])
    [Decimal('33.34'), Decimal('33.33'), Decimal('33.33')]
    """
    total_d = quantize_money(total)
    if total_d < ZERO:
        raise MoneyError("Cannot allocate a negative total.")
    weight_ds = [to_decimal(w) for w in weights]
    if not weight_ds:
        raise MoneyError("At least one weight is required.")
    if any(w < 0 for w in weight_ds):
        raise MoneyError("Weights cannot be negative.")
    weight_sum = sum(weight_ds, Decimal(0))
    if weight_sum == 0:
        raise MoneyError("Weights must not all be zero.")

    exact = [total_d * w / weight_sum for w in weight_ds]
    floored = [quantize_money(x, rounding=ROUND_DOWN) for x in exact]
    leftover_cents = int(((total_d - sum(floored, ZERO)) / CENT).to_integral_value())

    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floored[i]), i))
    for i in order[:leftover_cents]:
        floored[i] += CENT
    return floored
