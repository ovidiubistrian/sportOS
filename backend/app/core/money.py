"""Money.

Integer minor units and an ISO 4217 currency, always together. There is no
float constructor and no implicit cross-currency arithmetic, because both are
ways to lose money quietly.

The exponent comes from a table rather than a hardcoded 100: JPY has 0 decimals
and KWD/BHD/TND have 3. A hardcoded `/100` is a 1000x error in Kuwait.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Self

# Only currencies whose exponent is not 2. Everything else defaults to 2.
_EXPONENTS: Final[dict[str, int]] = {
    "BIF": 0, "CLP": 0, "DJF": 0, "GNF": 0, "ISK": 0, "JPY": 0, "KMF": 0,
    "KRW": 0, "PYG": 0, "RWF": 0, "UGX": 0, "UYI": 0, "VND": 0, "VUV": 0,
    "XAF": 0, "XOF": 0, "XPF": 0,
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
}

BASIS_POINTS: Final = 10_000


def exponent_for(currency: str) -> int:
    return _EXPONENTS.get(currency.upper(), 2)


class CurrencyMismatch(ValueError):
    pass


@dataclass(frozen=True, slots=True, order=False)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise TypeError("amount_minor must be an int in minor units")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError(f"invalid ISO 4217 currency: {self.currency!r}")
        object.__setattr__(self, "currency", self.currency.upper())

    # --- construction ----------------------------------------------------

    @classmethod
    def zero(cls, currency: str) -> Self:
        return cls(0, currency)

    @classmethod
    def from_decimal(cls, value: Decimal | str, currency: str) -> Self:
        """Parse a major-unit decimal. Never accepts float."""
        scale = 10 ** exponent_for(currency)
        minor = (Decimal(value) * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return cls(int(minor), currency)

    # --- inspection ------------------------------------------------------

    @property
    def exponent(self) -> int:
        return exponent_for(self.currency)

    def to_decimal(self) -> Decimal:
        return Decimal(self.amount_minor) / (10**self.exponent)

    @property
    def is_zero(self) -> bool:
        return self.amount_minor == 0

    # --- arithmetic ------------------------------------------------------

    def _check(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"cannot combine {self.currency} with {other.currency}"
            )

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __mul__(self, quantity: int) -> Money:
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise TypeError("money may only be multiplied by an integer quantity")
        return Money(self.amount_minor * quantity, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount_minor, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor < other.amount_minor

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor <= other.amount_minor

    # --- domain operations ------------------------------------------------

    def percentage(self, basis_points: int) -> Money:
        """A share expressed in basis points (250 = 2.50%), rounded half-up."""
        product = Decimal(self.amount_minor) * Decimal(basis_points) / BASIS_POINTS
        rounded = product.quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return Money(int(rounded), self.currency)

    def clamp(self, minimum: Money | None = None, maximum: Money | None = None) -> Money:
        result = self
        if minimum is not None and result < minimum:
            result = minimum
        if maximum is not None and maximum < result:
            result = maximum
        return result

    def allocate(self, weights: list[int]) -> list[Money]:
        """Split across weights so the parts always sum exactly to the whole.

        Largest-remainder distribution. Used for fee allocation and partial
        refunds, where a lost or invented minor unit is a reconciliation bug.
        """
        if not weights or any(w < 0 for w in weights):
            raise ValueError("weights must be a non-empty list of non-negative ints")
        total_weight = sum(weights)
        if total_weight == 0:
            raise ValueError("weights must not sum to zero")

        shares = [self.amount_minor * w // total_weight for w in weights]
        remainder = self.amount_minor - sum(shares)
        # Hand the leftover units to the largest fractional parts, deterministically.
        order = sorted(
            range(len(weights)),
            key=lambda i: (-(self.amount_minor * weights[i] % total_weight), i),
        )
        for i in range(remainder):
            shares[order[i % len(order)]] += 1
        return [Money(s, self.currency) for s in shares]

    def __str__(self) -> str:
        return f"{self.to_decimal()} {self.currency}"


def sum_money(items: list[Money], currency: str) -> Money:
    total = Money.zero(currency)
    for item in items:
        total += item
    return total
