"""Identifier generation.

UUIDv7 everywhere: time-ordered so B-tree inserts stay at the right edge of the
index (unlike UUIDv4, which scatters writes across the whole index), while still
being opaque and non-guessable in URLs.
"""

from __future__ import annotations

from uuid import UUID

import uuid_utils


def new_id() -> UUID:
    """A fresh time-ordered identifier."""
    return UUID(str(uuid_utils.uuid7()))


def id_from(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(value)
