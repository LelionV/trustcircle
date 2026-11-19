"""Pure calculator checks (no database): trust, risk, brackets and schedules."""
import random
from datetime import date
from decimal import Decimal as D

from apps.loans import calculators as L
from apps.risk_engine import calculators as R
from apps.trust_engine import calculators as T


def test_calculators_end_to_end():
    from apps.trust_engine import calculators as T
    from apps.risk_engine import calculators as R
    from apps.loans import calculators as L

    P = T.default_parameters(); T.validate_parameters(P)
    # --- trust: new verified borrower = 50
    r = T.calculate(T.TrustInputs(kyc_approved=True, email_verified=True, phone_verified=True), P)
    assert r["score"] == 50 and r["confidence"] == "NEW", r
    assert T.calculate(T.TrustInputs(kyc_approved=False), P)["score"] is None
    # punctuality bands
    for d, band in [(10,"early_7_plus"),(7,"early_7_plus"),(6,"early_3_6"),(3,"early_3_6"),(2,"early_1_2"),(1,"early_1_2"),(0,"on_time"),(-1,"late_1_3"),(-3,"late_1_3"),(-4,"late_4_7"),(-7,"late_4_7"),(-8,"late_8_14"),(-14,"late_8_14"),(-15,"late_15_plus")]:
        assert T.punctuality_band(d) == band, (d, band)
    # anti-gaming
    assert T.installment_points(days_early=8, amount_paid="400", amount_due="400", positive_points_used_on_loan=0, params=P)[0] is False
    assert T.installment_points(days_early=8, amount_paid="900", amount_due="1000", positive_points_used_on_loan=0, params=P)[0] is False
    assert T.installment_points(days_early=8, amount_paid="1000", amount_due="1000", positive_points_used_on_loan=22, params=P)[2] == 2
    # progression: spec example 50 -> ~75 -> ~90
    def borrower(n_inst, days, loans, age, defaults=0):
        inst = [(P["punctuality_points"][T.punctuality_band(days)], days >= 0)] * n_inst
        return T.TrustInputs(kyc_approved=True, email_verified=True, phone_verified=True, monthly_income=D("60000"),
                             monthly_obligations=D("10000"), income_verified=True, account_age_days=age,
                             installments=inst, completed_loans=loans, defaults=defaults)
    s1 = T.calculate(borrower(6, 8, 1, 200), P); s2 = T.calculate(borrower(12, 8, 2, 400), P)
    late = T.calculate(borrower(6, -5, 1, 200), P); dflt = T.calculate(borrower(6, -20, 0, 200, defaults=1), P)
    print("trust: after loan 1 early:", s1["score"], s1["confidence"], "| loan 2 early:", s2["score"], s2["confidence"],
          "| late payer:", late["score"], "| defaulter:", dflt["score"])
    assert 65 <= s1["score"] <= 80 and s2["score"] >= 90 and late["score"] < 50 and dflt["score"] < late["score"]
    # param validation
    bad = T.default_parameters(); bad["weights"]["kyc"] = 20
    try: T.validate_parameters(bad); raise AssertionError("weights not checked")
    except T.ParameterError as e: print("  rejects:", e)

    # --- risk
    RP = R.validate_parameters(R.default_parameters())
    good = R.calculate(R.RiskInputs(kyc_status="APPROVED", punctuality_score=100, monthly_income=D("60000"),
                        monthly_obligations=D("10000"), income_verified=True, employment_status="EMPLOYED"), RP)
    new = R.calculate(R.RiskInputs(kyc_status="APPROVED", monthly_income=D("30000"), monthly_obligations=D("12000"),
                       employment_status="SELF_EMPLOYED"), RP)
    bad = R.calculate(R.RiskInputs(kyc_status="NOT_SUBMITTED", defaults=2, open_loans=3, is_frozen=True, employment_status="UNEMPLOYED"), RP)
    print("risk: strong", good["score"], good["classification"], "| new", new["score"], new["classification"], "| bad", bad["score"], bad["classification"])
    assert good["classification"] == "VERY_LOW" and bad["classification"] == "CRITICAL"

    # --- brackets
    rows = L.validate_brackets([{"min_score":0,"max_score":19,"label":"Critical","annual_rate":None},
      {"min_score":20,"max_score":39,"label":"Very high risk","annual_rate":"22"},{"min_score":40,"max_score":59,"label":"High risk","annual_rate":"18"},
      {"min_score":60,"max_score":69,"label":"Fair","annual_rate":"15"},{"min_score":70,"max_score":79,"label":"Good","annual_rate":"12"},
      {"min_score":80,"max_score":89,"label":"Very good","annual_rate":"10"},{"min_score":90,"max_score":100,"label":"Excellent","annual_rate":"8"}])
    assert L.find_bracket(rows, 50)["annual_rate"] == D("18.00")
    nb = L.next_better_bracket(rows, 64); assert nb["min_score"] == 70 and nb["points_needed"] == 6
    assert L.next_better_bracket(rows, 95) is None
    for broken in ([{"min_score":0,"max_score":50,"label":"a","annual_rate":"10"},{"min_score":52,"max_score":100,"label":"b","annual_rate":"5"}],
                   [{"min_score":0,"max_score":60,"label":"a","annual_rate":"10"},{"min_score":50,"max_score":100,"label":"b","annual_rate":"5"}]):
        try: L.validate_brackets(broken); raise AssertionError("gap/overlap not caught")
        except L.BracketError as e: print("  rejects:", e)

    # --- schedules
    s = L.build_schedule(principal="10000", annual_rate="12", method="REDUCING_BALANCE", basis="ANNUAL", frequency="MONTHLY", term_months=12, start_date=date(2026,1,31))
    print("reducing 10k@12% 12m: installment", s["first_installment"], "interest", s["total_interest"], "due dates", s["installments"][0]["due_date"], s["installments"][1]["due_date"], s["final_due_date"])
    assert s["first_installment"] == D("888.49") and s["installments"][1]["due_date"] == date(2026,3,31) and s["installments"][0]["due_date"] == date(2026,2,28)
    f = L.build_schedule(principal="10000", annual_rate="18", method="FLAT", basis="ANNUAL", frequency="MONTHLY", term_months=6, start_date=date(2026,11,3))
    assert f["total_interest"] == D("900.00"), f["total_interest"]
    pl = L.build_schedule(principal="6000", annual_rate="3", method="REDUCING_BALANCE", basis="PER_LOAN", frequency="MONTHLY", term_months=1, start_date=date(2026,11,3))
    assert pl["total_interest"] == D("180.00") and pl["method"] == "FLAT"
    w = L.build_schedule(principal="5000", annual_rate="22", method="REDUCING_BALANCE", basis="ANNUAL", frequency="WEEKLY", term_months=3, start_date=date(2026,11,3))
    assert w["installment_count"] == 13
    random.seed(1)
    for _ in range(3000):
        p = D(random.randint(100000, 50000000)) / 100
        kw = dict(principal=p, annual_rate=D(random.randint(0, 3000))/100, method=random.choice(["FLAT","REDUCING_BALANCE"]),
                  basis=random.choice(["ANNUAL","MONTHLY","PER_LOAN"]), frequency=random.choice(["WEEKLY","BIWEEKLY","MONTHLY"]),
                  term_months=random.randint(1, 36), start_date=date(2026,1,31))
        sc = L.build_schedule(**kw)
        assert sum(i["principal"] for i in sc["installments"]) == L.money(p), kw
        assert sc["installments"][-1]["balance_after"] == 0
        assert all(i["principal"] >= 0 and i["interest"] >= 0 for i in sc["installments"]), kw
        assert sc["total_repayable"] == sum(i["total"] for i in sc["installments"])
    print("schedules: 3000 random loans add up exactly, no negative parts")
