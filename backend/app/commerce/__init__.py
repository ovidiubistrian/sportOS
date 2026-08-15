"""The club shop.

Importing this package registers the PRODUCT line handler with `ordering`, which
is what lets a shop line go through a checkout that knows nothing about scarves.
The import is here rather than in the router so the handler exists for anything
that touches commerce — a background job, a test, the seed script — not only for
a request that happened to hit an HTTP route.
"""

from app.commerce import handler as _handler  # noqa: F401
