"""The payment port: what the rest of the application is allowed to know.

One provider instance per `(tenant, provider)`, built from that tenant's own
credentials. Nothing outside this package imports a provider SDK or speaks a
provider's vocabulary — the types crossing this boundary are ours, and a
provider's own objects never escape its adapter. `docs/architecture/09-payments.md`
states the rule; this module is where it becomes enforceable.

Amounts are integer minor units in both directions. `app/core/money.py` explains
why at length; the short version is that a float here is a rounding error
somebody eventually has to refund.

Async throughout, because everything that calls it is: a provider that blocks
the event loop for the length of a bank's round trip would stall every other
request on the worker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import DomainError


class PaymentProviderError(DomainError):
    """The provider layer could not satisfy a request.

    Bad credentials, a network failure, an unsupported operation. A
    `DomainError` rather than a bare exception so it reaches the client as a
    sentence and a status code rather than as a 500 — a supporter whose card
    was refused is owed an explanation, not a stack trace.
    """

    code, status = "PAYMENT_PROVIDER_ERROR", 502
    default_message = "The payment provider could not be reached."


# What a checkout can be, once. Deliberately not the provider's own vocabulary:
# a caller decides what to do next from these four words and nothing else.
#
#   pending    registered, no attempt yet, or an authentication in progress
#   completed  the money has moved
#   approved   held but not captured — two-phase only, capture is a later act
#   failed     refused, by the issuer or the gateway
#   expired    the session lapsed without payment
#   refunded   returned, in full or in part
PAYMENT_STATES = (
    "pending",
    "completed",
    "approved",
    "failed",
    "expired",
    "refunded",
    "partially_refunded",
)


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    """A hosted checkout the buyer must be sent to."""

    session_id: str
    url: str
    expires_at: int | None = None  # unix seconds, as the provider reported it
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionStatus:
    """What the provider says about a session, in our words.

    `raw` is kept because the mapping is lossy on purpose and some callers
    need what was lost. Reconciliation is the one that matters: two provider
    states can map to the same word here and still have to be treated
    oppositely — see `BtIpayProvider` on order status 0 against 5.
    """

    status: str
    paid_amount_minor: int = 0
    currency: str = "RON"
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(ABC):
    """One instance per `(tenant, provider)`.

    Constructed from the tenant's parsed credentials; missing or malformed
    ones raise `PaymentProviderError` at construction rather than at the
    moment a supporter is trying to pay.
    """

    key: str = "base"
    display_name: str = "Payment Provider"

    @abstractmethod
    async def create_checkout_session(
        self,
        *,
        order_ref: str,
        amount_minor: int,
        currency: str,
        return_url: str,
        metadata: dict[str, str] | None = None,
        buyer_email: str | None = None,
    ) -> CheckoutSession:
        """Register a payment and return the URL to send the buyer to."""

    @abstractmethod
    async def get_session_status(self, session_id: str) -> SessionStatus:
        """Ask the provider what actually happened.

        The only thing that may confirm a payment. A buyer arriving back on
        the return URL proves they came back, and nothing else.
        """

    async def refund(self, session_id: str, amount_minor: int) -> dict[str, Any]:
        """Return money, in full or in part. Optional; the default refuses."""
        raise PaymentProviderError(f"{self.display_name} cannot refund from the application.")

    async def test_connection(self) -> dict[str, Any]:
        """Prove the credentials work, without taking a payment.

        For the settings screen: a club that has just pasted a user name and a
        password should find out immediately, not on its first sale.
        """
        raise PaymentProviderError(f"{self.display_name} has no connection test.")
