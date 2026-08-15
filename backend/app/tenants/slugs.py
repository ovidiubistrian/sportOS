"""Reserved slugs.

A club slug becomes a path on the platform host: `footbola.localhost/fc-example`.
The marketing pages and the platform areas live on that same host, so a slug
that collided with one of them would shadow it — a club called "pricing" would
either lose its workspace or take down the pricing page, depending on which
router won.

The list is deliberately wider than what is routed today. Slugs are permanent
in practice (they are in links, bookmarks and emails), so reserving a word we
might want later costs nothing, and failing to reserve one costs a migration
and a broken URL for a customer.
"""

from __future__ import annotations

RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        # Routed today.
        "signin",
        "signout",
        "auth",
        "platform",
        "pricing",
        "api",
        # Marketing and support pages we will want.
        "about",
        "blog",
        "contact",
        "docs",
        "features",
        "help",
        "legal",
        "privacy",
        "security",
        "status",
        "support",
        "terms",
        # Operational names that must never resolve to a customer.
        "admin",
        "app",
        "assets",
        "billing",
        "cdn",
        "console",
        "dashboard",
        "files",
        "internal",
        "login",
        "logout",
        "media",
        "new",
        "root",
        "settings",
        "static",
        "system",
        "www",
    }
)


def is_reserved(slug: str) -> bool:
    return slug.strip().lower() in RESERVED_SLUGS
