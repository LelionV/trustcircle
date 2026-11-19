"""
Repayment allocation and distribution: pure functions, Decimal only.

Allocation: a payment is applied to the oldest unpaid installment first and,
within an installment, in this order:
  late fee -> extension fee -> extension interest -> interest -> principal.

Distribution: every repayment is paid out at once. Principal goes back to
investors in proportion to their contributions (never more than each is
still owed). Collected interest (and extension interest) is split investor
pool / platform / guarantor by the configured percentages; the investor pool
is shared by contribution x the rate each investor lent at (the same rate for
everyone on a guaranteed loan). Every split is exact to the cent.
"""
from __future__ import annotations

from decimal import Decimal

from apps.common.money import ZERO, allocate, quantize_money

COMPONENTS = ("late_fee", "extension_fee", "extension_interest", "interest", "principal")


class AllocationError(ValueError):
    pass


def allocate_payment(amount, installments):
    """
    installments: ordered oldest first, each {"id", "<component>_due": Decimal, ...}
    Returns {"lines": [{"id", "<component>": paid, "cleared": bool}], "totals": {component: Decimal}}
    """
    remaining = quantize_money(amount)
    if remaining <= 0:
        raise AllocationError("Enter an amount greater than zero.")
    outstanding = sum((quantize_money(i[f"{c}_due"]) for i in installments for c in COMPONENTS), ZERO)
    if remaining > outstanding:
        raise AllocationError(f"That's more than the KES {outstanding:,.2f} still owed.")
    lines, totals = [], {c: ZERO for c in COMPONENTS}
    for inst in installments:
        if remaining == 0:
            break
        line = {"id": inst["id"]}
        due_left = ZERO
        for c in COMPONENTS:
            due = quantize_money(inst[f"{c}_due"])
            pay = min(due, remaining)
            line[c] = pay
            totals[c] += pay
            remaining -= pay
            due_left += due - pay
        line["cleared"] = due_left == 0
        if any(line[c] for c in COMPONENTS):
            lines.append(line)
    return {"lines": lines, "totals": totals}


def _split_capped(total, weights, caps):
    """Proportional split that never gives anyone more than their cap (exact to the cent)."""
    total = quantize_money(total)
    if total == 0 or not weights or sum(weights) == 0:
        return [ZERO] * len(weights)
    parts = allocate(total, weights)
    overflow = ZERO
    for i, cap in enumerate(caps):
        if parts[i] > cap:
            overflow += parts[i] - cap
            parts[i] = cap
    i = 0
    while overflow > 0 and i < len(parts):  # hand back any rounding overflow to those with room
        room = caps[i] - parts[i]
        give = min(room, overflow)
        parts[i] += give
        overflow -= give
        i += 1
    return parts


def _unpack(investments):
    """(key, outstanding[, contribution[, rate]]) -> keys, caps, principal weights, interest weights."""
    keys, caps, pw, iw = [], [], [], []
    for row in investments:
        key, outstanding = row[0], quantize_money(row[1])
        contribution = quantize_money(row[2]) if len(row) > 2 else outstanding
        rate = Decimal(str(row[3])) if len(row) > 3 and row[3] is not None else Decimal("1")
        keys.append(key)
        caps.append(outstanding)
        pw.append(contribution)
        iw.append(contribution * rate)
    return keys, caps, pw, iw


def distribute(*, principal, interest, extension_interest, investments, split, guarantor_eligible):
    """
    investments: [(key, outstanding_principal, contribution, rate)] before this payment
                 (contribution and rate are optional; they default to the outstanding amount and 1).
    Principal is shared by contribution (never more than an investor is still owed); the investors' share
    of interest by contribution x rate, so investors who lent at a higher rate earn proportionally more.
    When every investor has the same rate this is simply "according to their contributions".
    split: {"investors": %, "platform": %, "guarantor": %}
    Returns {"investors": {key: {"principal", "interest", "extension_interest"}},
             "platform": {"interest", "extension_interest"}, "guarantor": {"interest", "extension_interest"}}
    """
    keys, caps, pweights, iweights = _unpack(investments)
    if quantize_money(principal) > sum(caps, ZERO):
        raise AllocationError("Principal collected is more than investors are owed.")
    live = [w if c > 0 else ZERO for w, c in zip(pweights, caps)]
    weights = live if sum(live) else caps

    def three_way(amount):
        a = quantize_money(amount)
        if a == 0:
            return ZERO, ZERO, ZERO
        w = [split["investors"], split["platform"] + (0 if guarantor_eligible else split["guarantor"]),
             split["guarantor"] if guarantor_eligible else 0]
        if not keys:  # no investors (shouldn't happen): all to the platform
            return ZERO, a, ZERO
        return tuple(allocate(a, w))

    inv_i, plat_i, guar_i = three_way(interest)
    inv_e, plat_e, guar_e = three_way(extension_interest)
    p_parts = _split_capped(principal, weights, caps)
    iw = [w if c > 0 else 0 for w, c in zip(iweights, caps)]
    if not sum(iw):
        iw = iweights if sum(iweights) else [1] * len(keys)
    i_parts = allocate(inv_i, iw) if inv_i and keys else [ZERO] * len(keys)
    e_parts = allocate(inv_e, iw) if inv_e and keys else [ZERO] * len(keys)
    return {
        "investors": {k: {"principal": p_parts[n], "interest": i_parts[n], "extension_interest": e_parts[n]}
                      for n, k in enumerate(keys)},
        "platform": {"interest": plat_i, "extension_interest": plat_e},
        "guarantor": {"interest": guar_i, "extension_interest": guar_e},
    }


def split_recovery(amount, investments):
    """A recovery after default (e.g. from a guarantor) reduces investors' principal pro rata."""
    weights = [quantize_money(o) for _, o in investments]
    amount = min(quantize_money(amount), sum(weights, ZERO))
    parts = _split_capped(amount, weights, weights)
    return {k: parts[n] for n, (k, _) in enumerate(investments)}


def shift_schedule(due_dates, days):
    """New due dates when an extension moves every unpaid installment later by `days`."""
    from datetime import timedelta

    return [d + timedelta(days=days) for d in due_dates]


def installment_outcome(due_date, paid_on):
    """PAID_EARLY / PAID_ON_TIME / PAID_LATE for a fully paid installment."""
    days = (due_date - paid_on).days
    return "PAID_EARLY" if days > 0 else "PAID_ON_TIME" if days == 0 else "PAID_LATE"


def as_decimal(value) -> Decimal:
    return quantize_money(value)
