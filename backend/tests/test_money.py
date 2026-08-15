"""Money invariants.

Nothing in Phase 1 charges anyone, but these rules are cheaper to establish
before there is money flowing than after. Every one of them corresponds to a
way real systems have lost or invented money.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import BASIS_POINTS, CurrencyMismatch, Money, exponent_for


class TestConstruction:
    def test_floats_are_rejected(self) -> None:
        with pytest.raises(TypeError):
            Money(19.90, "EUR")  # type: ignore[arg-type]

    def test_booleans_are_not_integers_here(self) -> None:
        with pytest.raises(TypeError):
            Money(True, "EUR")  # type: ignore[arg-type]

    def test_currency_must_be_iso_4217(self) -> None:
        for bad in ("EU", "EURO", "12E", ""):
            with pytest.raises(ValueError, match="currency"):
                Money(100, bad)

    def test_currency_is_normalised(self) -> None:
        assert Money(100, "eur").currency == "EUR"

    def test_from_decimal_rounds_half_up(self) -> None:
        assert Money.from_decimal(Decimal("19.905"), "EUR").amount_minor == 1991
        assert Money.from_decimal("19.90", "EUR").amount_minor == 1990


class TestCurrencyExponents:
    """A hardcoded /100 is a 1000x error in Kuwait and a 100x error in Japan."""

    @pytest.mark.parametrize(
        ("currency", "expected"),
        [("EUR", 2), ("GBP", 2), ("RON", 2), ("JPY", 0), ("KWD", 3), ("BHD", 3)],
    )
    def test_exponent(self, currency: str, expected: int) -> None:
        assert exponent_for(currency) == expected

    def test_zero_decimal_currency_round_trips(self) -> None:
        money = Money.from_decimal("1500", "JPY")
        assert money.amount_minor == 1500
        assert money.to_decimal() == Decimal(1500)

    def test_three_decimal_currency_round_trips(self) -> None:
        money = Money.from_decimal("1.500", "KWD")
        assert money.amount_minor == 1500
        assert money.to_decimal() == Decimal("1.500")


class TestArithmetic:
    def test_cross_currency_arithmetic_raises(self) -> None:
        with pytest.raises(CurrencyMismatch):
            Money(100, "EUR") + Money(100, "GBP")

    def test_multiplication_requires_an_integer_quantity(self) -> None:
        assert (Money(1990, "EUR") * 3).amount_minor == 5970
        with pytest.raises(TypeError):
            Money(1990, "EUR") * 1.5  # type: ignore[operator]

    def test_percentage_uses_basis_points_and_rounds_half_up(self) -> None:
        # 2.50% of €100.00 = €2.50
        assert Money(10_000, "EUR").percentage(250).amount_minor == 250
        # 1% of €19.99 = 0.1999 -> 20 minor units
        assert Money(1999, "EUR").percentage(100).amount_minor == 20
        assert Money(10_000, "EUR").percentage(BASIS_POINTS).amount_minor == 10_000

    def test_clamp_applies_floor_and_ceiling(self) -> None:
        fee = Money(5, "EUR")
        assert fee.clamp(minimum=Money(50, "EUR")).amount_minor == 50
        assert Money(10_000, "EUR").clamp(maximum=Money(500, "EUR")).amount_minor == 500


class TestAllocation:
    """Splits must sum exactly to the whole — no lost or invented minor units."""

    @pytest.mark.parametrize(
        ("total", "weights"),
        [
            (100, [1, 1, 1]),
            (1, [1, 1]),
            (9999, [3, 5, 7, 11]),
            (5, [1, 0, 1]),
            (1_000_000, [1] * 7),
        ],
    )
    def test_parts_sum_to_the_whole(self, total: int, weights: list[int]) -> None:
        parts = Money(total, "EUR").allocate(weights)
        assert sum(p.amount_minor for p in parts) == total
        assert len(parts) == len(weights)

    def test_allocation_is_deterministic(self) -> None:
        first = Money(100, "EUR").allocate([1, 1, 1])
        second = Money(100, "EUR").allocate([1, 1, 1])
        assert first == second

    def test_zero_weights_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="sum to zero"):
            Money(100, "EUR").allocate([0, 0])
