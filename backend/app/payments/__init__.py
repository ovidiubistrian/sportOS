"""Card payments.

The only package that speaks a gateway's language. Everything else asks it for
a checkout session and is told what happened, in words of ours —
`docs/architecture/09-payments.md` sets the rule and `base.py` is the border.
"""

from app.payments.base import (
    CheckoutSession,
    PaymentProvider,
    PaymentProviderError,
    SessionStatus,
)
from app.payments.registry import build_provider, can_take_card, configured_providers

__all__ = [
    "CheckoutSession",
    "PaymentProvider",
    "PaymentProviderError",
    "SessionStatus",
    "build_provider",
    "can_take_card",
    "configured_providers",
]
