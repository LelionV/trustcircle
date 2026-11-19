"""Pure calculators for phases 5–8 (no database): fees, interest split, extension pricing, allocation, distribution."""
import random
from decimal import Decimal as D

import pytest

from apps.commissions import calculators as C
from apps.repayments import calculators as R

RULES = C.validate_parameters(C.default_parameters())
SPLIT = RULES["revenue_split"]


def test_fees_and_spec_examples():
    assert C.fee_for("withdrawal", D("1000"), RULES) == D("20.00")      # 1%, minimum 20
    assert C.fee_for("withdrawal", D("100000"), RULES) == D("300.00")   # capped at 300
    assert C.split_interest(D("120"), guarantor_eligible=True, params=RULES) == {"investors": D("90.00"), "platform": D("24.00"), "guarantor": D("6.00")}
    assert C.extension_charges(D("6000"), 30, RULES)["extension_interest"] == D("180.00")
    assert C.weighted_rate([(D("25000"), D("3")), (D("15000"), D("5"))]) == D("3.75")


def test_rules_validation_rejects_bad_split():
    p = C.default_parameters()
    p["revenue_split"] = {"investors": 80, "platform": 20, "guarantor": 10}
    with pytest.raises(C.RulesError):
        C.validate_parameters(p)


def test_allocation_order_and_overpayment():
    inst = [{"id": 1, "late_fee_due": D("10"), "extension_fee_due": D("0"), "extension_interest_due": D("5"), "interest_due": D("100"), "principal_due": D("900")},
            {"id": 2, "late_fee_due": D("0"), "extension_fee_due": D("0"), "extension_interest_due": D("0"), "interest_due": D("80"), "principal_due": D("920")}]
    a = R.allocate_payment(D("120"), inst)
    assert a["totals"]["late_fee"] == D("10") and a["totals"]["extension_interest"] == D("5") and a["totals"]["interest"] == D("100")
    assert a["totals"]["principal"] == D("5")
    with pytest.raises(R.AllocationError):
        R.allocate_payment(D("3000"), inst)


def test_distribution_is_exact_and_by_contribution_and_rate():
    rnd = random.Random(7)
    for _ in range(2000):
        n = rnd.randint(1, 6)
        contrib = [D(rnd.randint(500, 50000)) for _ in range(n)]
        rates = [D(rnd.choice(["1.5", "2", "3.25"])) for _ in range(n)]
        principal = min(sum(contrib), D(rnd.randint(1, 100000)))
        interest = D(rnd.randint(0, 20000)) / 100
        r = R.distribute(principal=principal, interest=interest, extension_interest=D("3.33"),
                         investments=[(i, contrib[i], contrib[i], rates[i]) for i in range(n)], split=SPLIT,
                         guarantor_eligible=rnd.random() < 0.5)
        assert sum(v["principal"] for v in r["investors"].values()) == principal.quantize(D("0.01"))
        total_i = sum(v["interest"] for v in r["investors"].values()) + r["platform"]["interest"] + r["guarantor"]["interest"]
        assert total_i == interest.quantize(D("0.01"))
    r = R.distribute(principal=D("400"), interest=D("100"), extension_interest=D("0"),
                     investments=[("a", D("1000"), D("1000"), D("2")), ("b", D("3000"), D("3000"), D("4"))],
                     split=SPLIT, guarantor_eligible=False)
    assert r["investors"]["a"]["principal"] == D("100.00") and r["investors"]["b"]["principal"] == D("300.00")
    assert r["investors"]["a"]["interest"] == D("10.71") and r["investors"]["b"]["interest"] == D("64.29")
