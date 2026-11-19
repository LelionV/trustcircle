"""
Platform rules: fees, limits, the revenue split, extension pricing and
overdue rules. Pure functions with no database access; the active
parameters come from the versioned PlatformRules table.

Every charge is computed here, shown to the user before they confirm, and
posted to the ledger as its own line so revenue can be reported by category.
"""
from __future__ import annotations

import copy
from decimal import Decimal

from apps.common.money import ZERO, allocate, quantize_money

FEE_KINDS = ("deposit", "withdrawal", "transfer")

DEFAULT_PARAMETERS = {
    "fees": {
        # type FIXED: value is KES. PERCENT: value is % of the amount, kept between min and max (max 0 = no cap).
        "deposit": {"type": "FIXED", "value": "0.00", "min": "0.00", "max": "0.00"},
        "withdrawal": {"type": "PERCENT", "value": "1.00", "min": "20.00", "max": "300.00"},
        "transfer": {"type": "FIXED", "value": "10.00", "min": "0.00", "max": "0.00"},
        "account_management_monthly": "0.00",
    },
    "limits": {
        "min_deposit": "100.00",
        "max_deposit": "500000.00",
        "min_withdrawal": "100.00",
        "max_withdrawal": "300000.00",
        "withdrawal_approval_threshold": "50000.00",
        "daily_withdrawal_limit": "500000.00",
        "min_investment": "500.00",
        "min_transfer": "50.00",
    },
    # Share of collected interest (must add up to 100).
    "revenue_split": {"investors": 75, "platform": 20, "guarantor": 5},
    "extension": {
        "additional_monthly_rate": "3.00",   # % of remaining principal per 30 days
        "fixed_fee": "0.00",
        "percent_fee": "0.00",               # % of remaining principal, once
        "max_extensions_per_loan": 2,
        "max_extension_days": 60,
        "allow_after_due_date": True,
        "investor_consent": "NEGATIVE",      # NONE | NEGATIVE (approve unless objections) | EXPLICIT (majority must agree)
        "consent_days": 3,
    },
    # Open-offers marketplace (loans without a guarantor). Rates use the bracket table's basis (per month by default).
    "offers": {
        "min_rate": "0.50",
        "max_rate": "10.00",
        "min_amount": "500.00",
    },
    # Guarantors lock the borrower's total interest in their wallet while they guarantee the loan.
    "guarantee": {
        "lock_interest": True,
        "max_exposure_income_multiple": "6",
    },
    "overdue": {
        "grace_days": 3,
        "late_fee_type": "PERCENT",          # FIXED | PERCENT (of the installment)
        "late_fee_value": "2.00",
        "default_after_days": 60,
        "reminder_days_before": 3,
    },
}


class RulesError(ValueError):
    pass


def default_parameters():
    return copy.deepcopy(DEFAULT_PARAMETERS)


def _money(value, name):
    try:
        v = quantize_money(value)
    except Exception as exc:  # noqa: BLE001
        raise RulesError(f"{name} must be an amount.") from exc
    if v < 0:
        raise RulesError(f"{name} can't be negative.")
    return str(v)


def validate_parameters(params: dict) -> dict:
    try:
        p = copy.deepcopy(params)
        fees = {}
        for kind in FEE_KINDS:
            f = p["fees"][kind]
            if f["type"] not in ("FIXED", "PERCENT"):
                raise RulesError(f"The {kind} fee must be fixed or a percentage.")
            fees[kind] = {"type": f["type"], "value": _money(f["value"], f"The {kind} fee"),
                          "min": _money(f.get("min", 0), f"The {kind} fee minimum"),
                          "max": _money(f.get("max", 0), f"The {kind} fee maximum")}
            if f["type"] == "PERCENT" and Decimal(fees[kind]["value"]) > 100:
                raise RulesError(f"The {kind} fee can't be more than 100%.")
        fees["account_management_monthly"] = _money(p["fees"].get("account_management_monthly", 0),
                                                    "The account fee")
        limits = {k: _money(p["limits"][k], k.replace("_", " ").capitalize()) for k in DEFAULT_PARAMETERS["limits"]}
        for lo, hi in (("min_deposit", "max_deposit"), ("min_withdrawal", "max_withdrawal")):
            if Decimal(limits[hi]) < Decimal(limits[lo]):
                raise RulesError(f"{hi.replace('_', ' ').capitalize()} must be at least the minimum.")
        split = {k: int(p["revenue_split"][k]) for k in ("investors", "platform", "guarantor")}
        if any(v < 0 for v in split.values()) or sum(split.values()) != 100:
            raise RulesError("The interest split must add up to 100%.")
        e = p["extension"]
        ext = {
            "additional_monthly_rate": _money(e["additional_monthly_rate"], "The extension rate"),
            "fixed_fee": _money(e["fixed_fee"], "The extension fee"),
            "percent_fee": _money(e["percent_fee"], "The extension percentage fee"),
            "max_extensions_per_loan": int(e["max_extensions_per_loan"]),
            "max_extension_days": int(e["max_extension_days"]),
            "allow_after_due_date": bool(e["allow_after_due_date"]),
            "investor_consent": e["investor_consent"],
            "consent_days": int(e["consent_days"]),
        }
        if ext["investor_consent"] not in ("NONE", "NEGATIVE", "EXPLICIT"):
            raise RulesError("Investor consent must be NONE, NEGATIVE or EXPLICIT.")
        if ext["max_extension_days"] < 1 or ext["max_extensions_per_loan"] < 0 or ext["consent_days"] < 1:
            raise RulesError("Extension limits must be positive.")
        o = p["overdue"]
        over = {
            "grace_days": int(o["grace_days"]),
            "late_fee_type": o["late_fee_type"],
            "late_fee_value": _money(o["late_fee_value"], "The late fee"),
            "default_after_days": int(o["default_after_days"]),
            "reminder_days_before": int(o["reminder_days_before"]),
        }
        if over["late_fee_type"] not in ("FIXED", "PERCENT"):
            raise RulesError("The late fee must be fixed or a percentage.")
        if over["default_after_days"] <= over["grace_days"]:
            raise RulesError("A loan can only default after the grace period.")
        of = p.get("offers", DEFAULT_PARAMETERS["offers"])
        offers = {"min_rate": _money(of["min_rate"], "The lowest offer rate"),
                  "max_rate": _money(of["max_rate"], "The highest offer rate"),
                  "min_amount": _money(of["min_amount"], "The smallest offer")}
        if Decimal(offers["max_rate"]) < Decimal(offers["min_rate"]) or Decimal(offers["max_rate"]) > 100:
            raise RulesError("The highest offer rate must be between the lowest rate and 100%.")
        gu = p.get("guarantee", DEFAULT_PARAMETERS["guarantee"])
        guarantee = {"lock_interest": bool(gu["lock_interest"]),
                     "max_exposure_income_multiple": _money(gu["max_exposure_income_multiple"],
                                                            "The guarantor exposure limit")}
        return {"fees": fees, "limits": limits, "revenue_split": split, "extension": ext, "overdue": over,
                "offers": offers, "guarantee": guarantee}
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, RulesError):
            raise
        raise RulesError(f"Missing or invalid setting: {exc}") from exc


def fee_for(kind: str, amount, params: dict) -> Decimal:
    """The charge for a deposit, withdrawal or transfer of `amount`."""
    rule = params["fees"][kind]
    amount = quantize_money(amount)
    if rule["type"] == "FIXED":
        return quantize_money(rule["value"])
    fee = quantize_money(amount * Decimal(rule["value"]) / 100)
    fee = max(fee, quantize_money(rule["min"]))
    if Decimal(rule["max"]) > 0:
        fee = min(fee, quantize_money(rule["max"]))
    return fee


def weighted_rate(offers) -> Decimal:
    """Amount-weighted average rate of accepted offers [(amount, rate)], to the cent."""
    total = sum((quantize_money(a) for a, _ in offers), ZERO)
    if total == 0:
        return ZERO
    return quantize_money(sum((quantize_money(a) * Decimal(str(r)) for a, r in offers), ZERO) / total)


def split_interest(interest, *, guarantor_eligible: bool, params: dict) -> dict:
    """Split collected interest into investor pool, platform and guarantor shares (exact to the cent)."""
    s = params["revenue_split"]
    weights = [s["investors"], s["platform"], s["guarantor"] if guarantor_eligible else 0]
    if not guarantor_eligible:
        # The guarantor's share goes to the platform when there's no eligible guarantor.
        weights[1] += s["guarantor"]
    if sum(weights) == 0 or quantize_money(interest) == ZERO:
        return {"investors": ZERO, "platform": ZERO, "guarantor": ZERO}
    investors, platform, guarantor = allocate(interest, weights)
    return {"investors": investors, "platform": platform, "guarantor": guarantor}


def extension_charges(remaining_principal, days: int, params: dict) -> dict:
    """
    Spec example: KES 6,000 remaining, 30 days at 3% a month -> KES 180 extension interest.
    """
    e = params["extension"]
    principal = quantize_money(remaining_principal)
    interest = quantize_money(principal * Decimal(e["additional_monthly_rate"]) / 100 * Decimal(days) / 30)
    fee = quantize_money(Decimal(e["fixed_fee"]) + principal * Decimal(e["percent_fee"]) / 100)
    return {"extension_interest": interest, "extension_fee": fee, "total": interest + fee}


def late_fee(installment_total, params: dict) -> Decimal:
    o = params["overdue"]
    if o["late_fee_type"] == "FIXED":
        return quantize_money(o["late_fee_value"])
    return quantize_money(quantize_money(installment_total) * Decimal(o["late_fee_value"]) / 100)
