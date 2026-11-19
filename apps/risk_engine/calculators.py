"""
Risk score: pure functions, no database access.

Risk is separate from trust: a higher trust score is better, a higher risk
score means more lending risk. Each factor gives 0 (no risk) to 100
(highest risk); the weighted average is the risk score, and the configured
thresholds turn it into a classification.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CLASSES = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "CRITICAL")
CLASS_LABELS = {"VERY_LOW": "Very low", "LOW": "Low", "MEDIUM": "Medium", "HIGH": "High", "CRITICAL": "Critical"}

FACTORS = (
    "repayment_history", "debt_to_income", "income_verification", "employment",
    "kyc", "defaults", "outstanding_loans", "suspicious_activity",
)
FACTOR_LABELS = {
    "repayment_history": "Repayment history",
    "debt_to_income": "Debt-to-income ratio",
    "income_verification": "Income verification",
    "employment": "Employment stability",
    "kyc": "Identity verification",
    "defaults": "Previous defaults",
    "outstanding_loans": "Existing loans and commitments",
    "suspicious_activity": "Suspicious activity",
}

DEFAULT_PARAMETERS = {
    "thresholds": [
        {"min": 0, "max": 20, "class": "VERY_LOW"},
        {"min": 21, "max": 40, "class": "LOW"},
        {"min": 41, "max": 60, "class": "MEDIUM"},
        {"min": 61, "max": 80, "class": "HIGH"},
        {"min": 81, "max": 100, "class": "CRITICAL"},
    ],
    "weights": {
        "repayment_history": 20, "debt_to_income": 20, "income_verification": 15, "employment": 10,
        "kyc": 10, "defaults": 15, "outstanding_loans": 5, "suspicious_activity": 5,
    },
}

EMPLOYMENT_RISK = {"EMPLOYED": 10, "SELF_EMPLOYED": 30, "RETIRED": 30, "STUDENT": 70, "UNEMPLOYED": 90}


class ParameterError(ValueError):
    pass


def default_parameters():
    return copy.deepcopy(DEFAULT_PARAMETERS)


def validate_parameters(params: dict) -> dict:
    try:
        p = copy.deepcopy(params)
        weights = {k: int(p["weights"][k]) for k in FACTORS}
        if any(w < 0 for w in weights.values()):
            raise ParameterError("Weights can't be negative.")
        if sum(weights.values()) != 100:
            raise ParameterError(f"Weights must add up to 100 (they add up to {sum(weights.values())}).")
        rows = [{"min": int(t["min"]), "max": int(t["max"]), "class": str(t["class"])} for t in p["thresholds"]]
        if [r["class"] for r in rows] != list(CLASSES):
            raise ParameterError("Thresholds must list Very low, Low, Medium, High and Critical in that order.")
        expected = 0
        for r in rows:
            if r["min"] != expected or r["max"] < r["min"]:
                raise ParameterError("Thresholds must cover 0–100 in order, with no gaps or overlaps.")
            expected = r["max"] + 1
        if expected != 101:
            raise ParameterError("Thresholds must end at 100.")
        return {"weights": weights, "thresholds": rows}
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ParameterError):
            raise
        raise ParameterError(f"Missing or invalid setting: {exc}") from exc


@dataclass
class RiskInputs:
    kyc_status: str = "NOT_SUBMITTED"
    punctuality_score: int | None = None      # trust punctuality component, 0–100
    monthly_income: Decimal | None = None
    monthly_obligations: Decimal = Decimal("0")
    income_verified: bool = False
    employment_status: str = ""
    defaults: int = 0
    open_loans: int = 0
    is_frozen: bool = False


def _round(value) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def factor_values(inputs: RiskInputs) -> dict:
    """{factor: (risk 0–100, explanation)}"""
    f = {}
    if inputs.punctuality_score is None:
        f["repayment_history"] = (50, "No repayment history yet")
    else:
        f["repayment_history"] = (100 - inputs.punctuality_score, f"Punctuality score {inputs.punctuality_score}")

    if inputs.monthly_income is None or Decimal(inputs.monthly_income) <= 0:
        f["debt_to_income"] = (90, "No income to compare commitments against")
    else:
        dti = Decimal(inputs.monthly_obligations) / Decimal(inputs.monthly_income)
        value = 10 if dti <= Decimal("0.3") else 45 if dti <= Decimal("0.5") else 70 if dti <= Decimal("0.7") else 90
        f["debt_to_income"] = (value, f"Commitments take {_round(dti * 100)}% of income")

    if inputs.monthly_income is None:
        f["income_verification"] = (90, "No income declared")
    elif inputs.income_verified:
        f["income_verification"] = (10, "Income verified")
    else:
        f["income_verification"] = (60, "Income declared, not verified")

    emp = inputs.employment_status or ""
    f["employment"] = (EMPLOYMENT_RISK.get(emp, 60), emp.replace("_", " ").capitalize() or "Not provided")

    kyc = {"APPROVED": (0, "Verified"), "PENDING": (60, "Waiting for review")}.get(
        inputs.kyc_status, (100, "Not verified"))
    f["kyc"] = kyc

    d = inputs.defaults
    f["defaults"] = (0 if d == 0 else 80 if d == 1 else 100, f"{d} default{'s' * (d != 1)}")

    n = inputs.open_loans
    f["outstanding_loans"] = ({0: 0, 1: 40, 2: 70}.get(n, 100), f"{n} open loan{'s' * (n != 1)}")

    f["suspicious_activity"] = (100, "Account frozen") if inputs.is_frozen else (0, "None recorded")
    return f


def classify(score: int, params: dict) -> str:
    for row in params["thresholds"]:
        if row["min"] <= score <= row["max"]:
            return row["class"]
    return "CRITICAL"


def calculate(inputs: RiskInputs, params: dict) -> dict:
    values = factor_values(inputs)
    weights = params["weights"]
    total_w = sum(weights[k] for k in FACTORS) or 1
    score = _round(Decimal(sum(weights[k] * values[k][0] for k in FACTORS)) / total_w)
    return {
        "score": score,
        "classification": classify(score, params),
        "factors": [
            {"key": k, "label": FACTOR_LABELS[k], "weight": weights[k], "risk": values[k][0], "detail": values[k][1]}
            for k in FACTORS
        ],
    }
