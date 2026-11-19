from decimal import Decimal

import pytest

from apps.common.money import MoneyError, allocate, percentage_of, quantize_money, to_decimal


def test_floats_are_rejected():
    with pytest.raises(MoneyError):
        to_decimal(0.1)


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", True])
def test_invalid_amounts_are_rejected(bad):
    with pytest.raises(MoneyError):
        to_decimal(bad)


def test_quantize_rounds_half_up_to_cents():
    assert quantize_money("10.005") == Decimal("10.01")
    assert quantize_money("10.004") == Decimal("10.00")
    assert quantize_money(5) == Decimal("5.00")


def test_extension_interest_example_from_spec():
    # Remaining principal KES 6,000 x 3% = KES 180
    assert percentage_of("6000", "3") == Decimal("180.00")


def test_revenue_split_example_from_spec():
    # Collected interest KES 120 split 75 / 20 / 5
    assert allocate("120", [75, 20, 5]) == [Decimal("90.00"), Decimal("24.00"), Decimal("6.00")]


def test_pooled_contributions_example_from_spec():
    # Investors A-D funded 4000/3000/2000/1000 of KES 10,000.
    shares = allocate("90.00", [4000, 3000, 2000, 1000])
    assert shares == [Decimal("36.00"), Decimal("27.00"), Decimal("18.00"), Decimal("9.00")]


@pytest.mark.parametrize(
    "total, weights",
    [
        ("100.00", [1, 1, 1]),
        ("0.05", [1, 1, 1, 1, 1, 1, 1]),
        ("1234.57", ["3333.33", "1.01", "999999.99"]),
        ("0.00", [1, 2]),
        ("10.00", [0, 5]),
    ],
)
def test_allocation_always_sums_exactly(total, weights):
    parts = allocate(total, weights)
    assert sum(parts) == Decimal(total)
    assert all(p >= 0 for p in parts)


def test_allocation_leftover_cent_is_deterministic():
    assert allocate("100.00", [1, 1, 1]) == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]


@pytest.mark.parametrize("weights", [[], [0, 0], [-1, 2]])
def test_allocation_rejects_bad_weights(weights):
    with pytest.raises(MoneyError):
        allocate("10", weights)
