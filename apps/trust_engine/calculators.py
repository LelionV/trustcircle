"""
Trust score calculation: pure functions, no database access.

How the score works (explained to borrowers on the Trust score page):

1. Seven components, each scored 0–100, combined using the configured
   weights (punctuality 35, consistency 20, KYC 15, income 10, account
   history 5, loan completion 10, guarantor reliability 5). A component with
   no data yet ("not scored") is left out; its weight isn't counted, so no
   history is ever invented.
2. A new borrower starts at the initial score (50) once their identity is
   verified. Repayment history blends in gradually: after N scheduled
   installments (12 by default) the weighted components fully decide the
   score. That blend is the "confidence".
3. Defaults, extensions and audited manual adjustments are then applied as
   points, and the result is kept within 0–100.

Punctuality points per scheduled installment (configurable):
  7+ days early +4, 3–6 early +3, 1–2 early +2, on the due date +1,
  1–3 late −2, 4–7 late −5, 8–14 late −8, over 14 late −12.
Only installments paid in full and at least the minimum amount count, and
positive points from any one loan are capped, so many small or repeated
payments can't inflate the score.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

COMPONENTS = ("punctuality", "consistency", "kyc", "income", "account_history", "completion", "guarantor")

COMPONENT_LABELS = {
    "punctuality": "Repayment punctuality",
    "consistency": "Repayment consistency",
    "kyc": "Identity verification",
    "income": "Verified income and affordability",
    "account_history": "Account history",
    "completion": "Loan completion history",
    "guarantor": "Guarantor reliability",
}

PUNCTUALITY_BANDS = (
    "early_7_plus", "early_3_6", "early_1_2", "on_time", "late_1_3", "late_4_7", "late_8_14", "late_15_plus",
)

DEFAULT_PARAMETERS = {
    "initial_score": 50,
    "weights": {
        "punctuality": 35, "consistency": 20, "kyc": 15, "income": 10,
        "account_history": 5, "completion": 10, "guarantor": 5,
    },
    "punctuality_points": {
        "early_7_plus": 4, "early_3_6": 3, "early_1_2": 2, "on_time": 1,
        "late_1_3": -2, "late_4_7": -5, "late_8_14": -8, "late_15_plus": -12,
    },
    "default_penalty": 25,
    "reward_cap_per_loan": 24,
    "min_installment_amount": "500.00",
    "full_confidence_installments": 12,
    "extension_penalties": {"before_due": 0, "after_missed": 3, "repeat_extra": 2},
    # Finishing a whole loan early: bonus points when the last payment comes at least min_days before the
    # final due date (on top of the per-installment early-payment points above).
    "early_completion_bonus": {"min_days_early": 7, "points": 3},
    "manual_adjustment_limit": 20,
}


class ParameterError(ValueError):
    pass


def default_parameters():
    return copy.deepcopy(DEFAULT_PARAMETERS)


def validate_parameters(params: dict) -> dict:
    """Return a cleaned copy or raise ParameterError with a readable message."""
    try:
        p = copy.deepcopy(params)
        p["initial_score"] = int(p["initial_score"])
        if not 0 <= p["initial_score"] <= 100:
            raise ParameterError("The starting score must be between 0 and 100.")

        weights = {k: int(p["weights"][k]) for k in COMPONENTS}
        if any(w < 0 for w in weights.values()):
            raise ParameterError("Weights can't be negative.")
        if sum(weights.values()) != 100:
            raise ParameterError(f"Weights must add up to 100 (they add up to {sum(weights.values())}).")
        p["weights"] = weights

        points = {k: int(p["punctuality_points"][k]) for k in PUNCTUALITY_BANDS}
        ordered = [points[k] for k in PUNCTUALITY_BANDS]
        if ordered != sorted(ordered, reverse=True):
            raise ParameterError("Punctuality points must go down from 'earliest' to 'latest'.")
        if points["on_time"] < 0 or points["late_1_3"] > 0:
            raise ParameterError("On-time payments can't lose points and late payments can't earn them.")
        p["punctuality_points"] = points

        for key in ("default_penalty", "reward_cap_per_loan", "manual_adjustment_limit"):
            p[key] = int(p[key])
            if p[key] < 0:
                raise ParameterError(f"{key.replace('_', ' ').capitalize()} can't be negative.")
        p["full_confidence_installments"] = int(p["full_confidence_installments"])
        if p["full_confidence_installments"] < 1:
            raise ParameterError("Full confidence needs at least one installment.")
        minimum = Decimal(str(p["min_installment_amount"]))
        if minimum < 0:
            raise ParameterError("The minimum installment can't be negative.")
        p["min_installment_amount"] = str(minimum.quantize(Decimal("0.01")))
        ext = {k: int(p["extension_penalties"][k]) for k in ("before_due", "after_missed", "repeat_extra")}
        if any(v < 0 for v in ext.values()):
            raise ParameterError("Extension penalties are points taken off, so they can't be negative.")
        p["extension_penalties"] = ext
        early = p.get("early_completion_bonus", DEFAULT_PARAMETERS["early_completion_bonus"])
        early = {"min_days_early": int(early["min_days_early"]), "points": int(early["points"])}
        if early["min_days_early"] < 1 or early["points"] < 0:
            raise ParameterError("The early-completion bonus needs at least 1 day early and points of 0 or more.")
        p["early_completion_bonus"] = early
        return p
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        if isinstance(exc, ParameterError):
            raise
        raise ParameterError(f"Missing or invalid setting: {exc}") from exc


def punctuality_band(days_early: int) -> str:
    """days_early = due date − date paid (negative when late)."""
    if days_early >= 7:
        return "early_7_plus"
    if days_early >= 3:
        return "early_3_6"
    if days_early >= 1:
        return "early_1_2"
    if days_early == 0:
        return "on_time"
    if days_early >= -3:
        return "late_1_3"
    if days_early >= -7:
        return "late_4_7"
    if days_early >= -14:
        return "late_8_14"
    return "late_15_plus"


def installment_points(*, days_early, amount_paid, amount_due, positive_points_used_on_loan, params):
    """
    Points an installment counts for, and whether it counts at all.

    Returns (counted: bool, raw_points: int, counted_points: int, note: str).
    """
    minimum = Decimal(str(params["min_installment_amount"]))
    raw = params["punctuality_points"][punctuality_band(days_early)]
    if Decimal(str(amount_paid)) < Decimal(str(amount_due)):
        return False, raw, 0, "Not counted: the installment wasn't paid in full."
    if Decimal(str(amount_due)) < minimum:
        return False, raw, 0, f"Not counted: installments under KES {minimum} don't affect the score."
    if raw > 0:
        room = max(0, params["reward_cap_per_loan"] - positive_points_used_on_loan)
        counted = min(raw, room)
        note = "" if counted == raw else "Reward limit for this loan reached."
        return True, raw, counted, note
    return True, raw, raw, ""


@dataclass
class TrustInputs:
    kyc_approved: bool
    email_verified: bool = False
    phone_verified: bool = False
    monthly_income: Decimal | None = None
    monthly_obligations: Decimal = Decimal("0")
    income_verified: bool = False
    account_age_days: int = 0
    installments: list = field(default_factory=list)  # [(counted_points, paid_on_or_before_due)]
    early_payments: int = 0
    on_time_payments: int = 0
    late_payments: int = 0
    completed_loans: int = 0
    defaults: int = 0
    extension_points: int = 0      # total points taken off for extensions
    manual_points: int = 0         # sum of audited manual adjustments
    early_completion_points: int = 0  # bonuses for loans repaid in full well before the final due date


def _clamp(value, low=0, high=100):
    return max(Decimal(low), min(Decimal(high), Decimal(value)))


def _round(value) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def debt_to_income(income, obligations):
    if income is None or Decimal(income) <= 0:
        return None
    return Decimal(obligations) / Decimal(income)


def components(inputs: TrustInputs, params: dict) -> dict:
    result = {}
    n = len(inputs.installments)

    if n:
        mean = Decimal(sum(p for p, _ in inputs.installments)) / n
        result["punctuality"] = (_clamp(50 + mean * Decimal("12.5")),
                                 f"Average {mean.quantize(Decimal('0.1'))} points over {n} installment{'s' * (n != 1)}")
        on_time = sum(1 for _, ok in inputs.installments if ok)
        result["consistency"] = (_clamp(Decimal(on_time) * 100 / n),
                                 f"{on_time} of {n} paid on or before the due date")
    else:
        result["punctuality"] = (None, "No installments paid yet")
        result["consistency"] = (None, "No installments paid yet")

    if inputs.kyc_approved:
        kyc = 70 + (15 if inputs.email_verified else 0) + (15 if inputs.phone_verified else 0)
        missing = [x for x, ok in (("email", inputs.email_verified), ("phone", inputs.phone_verified)) if not ok]
        result["kyc"] = (Decimal(kyc), "Identity verified" + (f"; {' and '.join(missing)} not verified" if missing else
                                                               ", with email and phone"))
    else:
        result["kyc"] = (Decimal(0), "Identity not verified")

    dti = debt_to_income(inputs.monthly_income, inputs.monthly_obligations)
    if inputs.monthly_income is None:
        result["income"] = (Decimal(0), "No income declared")
    elif not inputs.income_verified:
        result["income"] = (Decimal(30), "Income declared but not verified")
    elif dti is None:
        result["income"] = (Decimal(20), "Verified income is zero")
    else:
        score = 100 if dti <= Decimal("0.3") else 70 if dti <= Decimal("0.5") else 40
        result["income"] = (Decimal(score), f"Verified income; commitments take {_round(dti * 100)}% of it")

    years = Decimal(inputs.account_age_days) / 365
    result["account_history"] = (_clamp(years * 100), f"Account {inputs.account_age_days} days old")

    if inputs.completed_loans or inputs.defaults:
        score = _clamp(inputs.completed_loans * 34 - inputs.defaults * 50)
        result["completion"] = (score, f"{inputs.completed_loans} completed, {inputs.defaults} defaulted")
    else:
        result["completion"] = (None, "No loans finished yet")

    result["guarantor"] = (None, "Scored once guarantees are in use")
    return result


def confidence(installment_count, completed_loans, params):
    full = params["full_confidence_installments"]
    share = min(Decimal(1), Decimal(installment_count) / full)
    if installment_count == 0 and completed_loans == 0:
        label = "NEW"
    elif share < Decimal("0.34"):
        label = "LOW"
    elif share < 1:
        label = "MEDIUM"
    else:
        label = "HIGH"
    return share, label


def calculate(inputs: TrustInputs, params: dict) -> dict:
    """
    Returns {"score": int | None, "confidence": str, "weighted": int | None,
             "components": [...], "adjustments": [...]}.
    The score is None until identity is verified.
    """
    comps = components(inputs, params)
    weights = params["weights"]
    rows = []
    total_w = Decimal(0)
    total = Decimal(0)
    for name in COMPONENTS:
        score, detail = comps[name]
        rows.append({
            "key": name, "label": COMPONENT_LABELS[name], "weight": weights[name],
            "score": None if score is None else _round(score), "detail": detail,
        })
        if score is not None and weights[name]:
            total_w += weights[name]
            total += weights[name] * score
    weighted = (total / total_w) if total_w else Decimal(params["initial_score"])

    n = len(inputs.installments)
    share, conf_label = confidence(n, inputs.completed_loans, params)

    if not inputs.kyc_approved:
        return {"score": None, "confidence": "NEW", "weighted": None, "components": rows, "adjustments": [],
                "blend": 0}

    blended = (1 - share) * Decimal(params["initial_score"]) + share * weighted
    adjustments = []
    if inputs.defaults:
        adjustments.append({"label": f"Default penalty ({inputs.defaults})",
                            "points": -params["default_penalty"] * inputs.defaults})
    if inputs.extension_points:
        adjustments.append({"label": "Repayment extensions", "points": -inputs.extension_points})
    if inputs.early_completion_points:
        adjustments.append({"label": "Loans repaid early", "points": inputs.early_completion_points})
    if inputs.manual_points:
        adjustments.append({"label": "Manual adjustments by administrators", "points": inputs.manual_points})
    final = _clamp(blended + sum(Decimal(a["points"]) for a in adjustments))
    return {
        "score": _round(final),
        "confidence": conf_label,
        "weighted": _round(weighted),
        "blend": _round(share * 100),
        "components": rows,
        "adjustments": adjustments,
    }
