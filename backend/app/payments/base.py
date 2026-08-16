"""The payment-provider port.

One implementation per acquirer, one instance per (tenant, provider), built
from that tenant's own credentials. Nothing outside this package imports an
acquirer's SDK or knows its wire format.

Two things are deliberately in the shape of the port rather than left to each
implementation:

`amount_minor` everywhere. A payment amount never becomes a float, not even
briefly, not even for display. The rest of the codebase already works this way
(`app/core/money.py`); the boundary with a bank is the last place to relax it.

`poll` as a first-class operation, not a fallback. Some acquirers notify us
asynchronously and some — BT iPay among them — never do. A port that treats
polling as the exception forces the ones that cannot notify into a shape that
loses payments, so it is the webhook that is optional here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PaymentProviderError(Exception):
    """The provider layer could not satisfy a request.

    Bad credentials, a network failure, an unsupported operation. Callers are
    expected to catch it and say something a supporter can act on — never to
    let it become a 500, and never to interpret it as "not paid".
    """


class PaymentState(StrEnum):
    """What the acquirer says about an attempt, in our vocabulary.

    Deliberately not the union of every acquirer's status list. `HELD` and
    `SETTLED` are distinct because the difference decides whether a club has
    the money; `PENDING` and `UNSTARTED` because the difference decides whether
    an order may be cancelled.
    """

    UNSTARTED = "UNSTARTED"  # registered, nobody has tried to pay
    PENDING = "PENDING"  # in flight — 3-D Secure, most likely
    HELD = "HELD"  # authorised, funds reserved, not captured
    SETTLED = "SETTLED"  # captured; the club has the money
    FAILED = "FAILED"  # declined
    REVERSED = "REVERSED"  # authorisation voided before capture
    REFUNDED = "REFUNDED"
    PART_REFUNDED = "PART_REFUNDED"

    @property
    def is_final(self) -> bool:
        return self in {
            PaymentState.SETTLED,
            PaymentState.FAILED,
            PaymentState.REVERSED,
            PaymentState.REFUNDED,
            PaymentState.PART_REFUNDED,
        }

    @property
    def may_cancel(self) -> bool:
        """Whether an order on this attempt is safe to expire.

        `PENDING` and `HELD` are not: one is a supporter part-way through their
        bank's authentication, the other is money already reserved on their
        card. Cancelling either takes an order away from somebody who is in the
        middle of paying for it, or has.
        """
        return self in {PaymentState.UNSTARTED, PaymentState.FAILED, PaymentState.REVERSED}


@dataclass(frozen=True, slots=True)
class Checkout:
    """Where to send the supporter, and what to remember them by."""

    reference: str
    """The acquirer's own id for the attempt. Stored, polled, refunded by."""

    redirect_url: str
    """The acquirer's hosted page. We never see card details."""

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Outcome:
    """What an attempt came to."""

    state: PaymentState
    paid_minor: int = 0
    currency: str = "RON"

    # Everything below is for reconciliation against the club's bank
    # statement. A club treasurer matching a line on the statement to an order
    # in the shop needs these, and they are unavailable later: the acquirer
    # keeps them for a while, the statement forever.
    rrn: str | None = None
    approval_code: str | None = None
    card_masked: str | None = None
    card_holder: str | None = None
    terminal_id: str | None = None
    authorised_at: Any = None

    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(ABC):
    """One acquirer, holding one tenant's credentials."""

    key: str = "base"
    display_name: str = "Payment provider"

    #: False where the acquirer has no asynchronous callback at all, and the
    #: only way to learn an outcome is to ask. Read by the reconciliation job.
    supports_notifications: bool = False

    @abstractmethod
    async def start(
        self,
        *,
        order_ref: str,
        amount_minor: int,
        currency: str,
        return_url: str,
        description: str,
        buyer: Buyer | None = None,
    ) -> Checkout:
        """Register an attempt and return where to send the supporter."""

    @abstractmethod
    async def poll(self, reference: str) -> Outcome:
        """Ask the acquirer what became of an attempt.

        The only thing anywhere that is allowed to conclude that an order was
        paid. Landing back on our return URL proves the supporter's browser
        came back, which is not the same claim.
        """

    async def refund(self, reference: str, amount_minor: int) -> dict[str, Any]:
        raise PaymentProviderError(f"{self.display_name} cannot refund from here yet.")

    async def capture(self, reference: str, amount_minor: int) -> dict[str, Any]:
        raise PaymentProviderError(f"{self.display_name} does not hold funds separately.")

    async def void(self, reference: str) -> dict[str, Any]:
        raise PaymentProviderError(f"{self.display_name} does not hold funds separately.")

    @abstractmethod
    async def check_credentials(self) -> CredentialCheck:
        """Prove the credentials work, without taking a payment.

        Exists so a club can tell a typo from a bank that has not finished
        onboarding it, on the screen where they pasted the credentials, rather
        than by discovering that no supporter can check out.
        """


@dataclass(frozen=True, slots=True)
class Buyer:
    """What the acquirer wants to know about the person paying.

    Every field optional, and meant literally: acquirers reject an address
    block containing `N/A` as readily as a malformed one, so a field we do not
    have is a field we do not send.
    """

    email: str | None = None
    phone: str | None = None
    city: str | None = None
    address: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class CredentialCheck:
    ok: bool
    message: str
    sandbox: bool = True
    raw: dict[str, Any] = field(default_factory=dict)
