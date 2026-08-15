"""Handler registry.

Handlers declare what they consume; the relay looks up subscribers by event
type. Registration happens at import time via `app/events/handlers_registry.py`,
so the wiring is one file rather than scattered imports.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.events.base import EVENT_TYPES, DomainEvent

Handler = Callable[[DomainEvent], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Subscription:
    name: str
    event_type: str
    handler: Handler


_SUBSCRIPTIONS: dict[str, list[Subscription]] = defaultdict(list)


def handles(event_class: type[DomainEvent]) -> Callable[[Handler], Handler]:
    """Register a handler for an event type.

    The handler's qualified name becomes its idempotency key in
    `processed_event`, so renaming a handler function replays its history —
    deliberate, and documented where it matters.
    """

    def decorator(handler: Handler) -> Handler:
        event_type = event_class.event_type
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"{event_class.__name__} is not in the event catalogue; "
                "add it to app/events/base.py so publishers and consumers agree."
            )
        name = f"{handler.__module__}.{handler.__qualname__}"
        if any(s.name == name for s in _SUBSCRIPTIONS[event_type]):
            raise ValueError(f"Handler {name} is already registered for {event_type}")
        _SUBSCRIPTIONS[event_type].append(Subscription(name, event_type, handler))
        return handler

    return decorator


def subscribers_for(event_type: str) -> list[Subscription]:
    return list(_SUBSCRIPTIONS.get(event_type, ()))


def all_subscriptions() -> list[Subscription]:
    return [s for subs in _SUBSCRIPTIONS.values() for s in subs]


def clear_registry() -> None:
    """Test-only."""
    _SUBSCRIPTIONS.clear()
