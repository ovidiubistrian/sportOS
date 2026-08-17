"""Stadium and ticketing.

Four layers, in the order they depend on each other:

    venue_models   the stadium master - drawn, versioned, published
    event_models   a match's frozen copy of it, and what is for sale
    ticket_models  what a supporter holds: entitlement, ticket, credential
    access_models  the turnstiles, and every scan they recorded

The rule that separates the first two is in `event_models`, and it is the one
worth knowing before reading anything else: **the live venue configuration is
never match inventory.**

Importing this package registers the TICKET and SEASON_TICKET line handlers
with `ordering`, the same way `commerce` registers PRODUCT. It belongs here
rather than in a router so the handlers exist for anything that touches
ticketing — the seed script, a maintenance job, a test — and not only for a
request that happened to reach an HTTP route.
"""

from app.ticketing import ordering_handlers as _ordering_handlers  # noqa: F401
