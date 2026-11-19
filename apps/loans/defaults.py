"""
Initial interest-bracket configuration from the platform specification.

These rows become version 1 of the admin-editable, versioned
``InterestBracketSet`` the first time pricing is needed. After that,
administrators change brackets from the Configuration page; this file is
only the starting point.
"""
from decimal import Decimal

INITIAL_BRACKET_SET_NAME = "Initial configuration"

# (min_score, max_score, label, rate or None for manual review).
# Rates are % PER MONTH (INITIAL_RATE_BASIS); administrators can switch the
# table to per-year or per-loan rates when they publish a new version.
INITIAL_RATE_BASIS = "MONTHLY"
INITIAL_INTEREST_BRACKETS = [
    (90, 100, "Excellent", Decimal("1.50")),
    (80, 89, "Very good", Decimal("2.00")),
    (70, 79, "Good", Decimal("2.50")),
    (60, 69, "Fair", Decimal("3.00")),
    (40, 59, "High risk", Decimal("3.50")),
    (20, 39, "Very high risk", Decimal("4.50")),
    (0, 19, "Critical", None),
]

INITIAL_NEW_BORROWER_SCORE = 50


DEFAULT_PRODUCT = {
    "name": "Personal loan",
    "description": "For personal, family and small business needs. Repay weekly, every two weeks or monthly.",
    "min_amount": Decimal("1000.00"),
    "max_amount": Decimal("200000.00"),
    "min_term_months": 1,
    "max_term_months": 12,
    "frequencies": ["WEEKLY", "BIWEEKLY", "MONTHLY"],
    "interest_method": "REDUCING_BALANCE",
    "rate_basis": "MONTHLY",
    "requires_guarantor": True,
    "funding_period_days": 14,
    "max_installment_share": Decimal("50.00"),
    "max_open_loans": 1,
}
