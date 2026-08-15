"""Field allow-list for audit payloads.

Fail-closed by construction: an object type with no entry records **no** field
values, and a field that is not listed is dropped. The alternative — a deny-list
— fails open the moment someone adds a column, which is exactly how card
numbers and diagnoses end up in an audit table.

`tests/audit/test_redaction.py` asserts the closed behaviour, including that
adding a sensitive-looking field to an existing type does not leak it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# object_type -> fields that may be recorded in `before` / `after`.
ALLOWED_FIELDS: Mapping[str, frozenset[str]] = {
    "player": frozenset(
        {
            "status",
            "primary_position",
            "secondary_positions",
            "preferred_foot",
            "federation_id",
            "joined_club_on",
            "left_club_on",
            "club_id",
        }
    ),
    "person": frozenset({"first_name", "last_name", "display_name", "preferred_locale"}),
    "player_registration": frozenset(
        {"team_id", "season_id", "shirt_number", "kind", "registered_on", "ended_on"}
    ),
    "team": frozenset({"name", "code", "gender", "age_group", "level", "status"}),
    "club": frozenset({"display_name", "short_name", "status", "currency", "timezone"}),
    "club_branding": frozenset(
        {
            "template",
            "color_mode",
            "color_primary",
            "color_secondary",
            "color_accent",
            "tagline",
            "crest_media_id",
            "hero_media_id",
        }
    ),
    "tenant": frozenset(
        {
            "status",
            "default_currency",
            "default_locale",
            "supported_locales",
            "timezone",
        }
    ),
    "role_assignment": frozenset(
        {"user_id", "role_id", "tenant_id", "club_id", "team_id", "revoked_at"}
    ),
    "tenant_subscription": frozenset(
        {"plan_version_id", "status", "current_period_end", "cancel_at"}
    ),
    "entitlement": frozenset({"feature_key", "enabled", "limit_value", "source", "reason"}),
    # Never the storage key or the original filename: the first is an
    # address and the second can itself be personal data.
    "media_asset": frozenset({"purpose", "visibility", "size_bytes", "alt_text"}),
    # Deliberately absent, and to stay absent:
    #   medical.*        clinical detail is never written to a general audit table;
    #                    the fact of access is recorded, the content is not.
    #   payment, card    provider references only, added with the payments module.
}

# Never recorded, whatever object type claims them. A second barrier so a typo
# in ALLOWED_FIELDS cannot expose a credential.
NEVER_RECORD = frozenset(
    {
        "password",
        "password_hash",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "secret_hash",
        "card_number",
        "pan",
        "cvc",
        "iban",
        "diagnosis",
        "diagnosis_code",
        "diagnosis_text",
        "notes_encrypted",
    }
)


def redact(object_type: str, values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Keep only explicitly allowed fields for this object type."""
    if not values:
        return None
    allowed = ALLOWED_FIELDS.get(object_type)
    if not allowed:
        return None
    return {
        key: _coerce(value)
        for key, value in values.items()
        if key in allowed and key not in NEVER_RECORD
    }


def _coerce(value: Any) -> Any:
    """Make a value JSON-safe without importing domain types."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_coerce(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)


def diff(
    object_type: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Redact both sides and drop fields that did not actually change.

    Storing only the delta keeps the table small and makes "what changed?"
    answerable at a glance instead of by comparing two large objects.
    """
    clean_before = redact(object_type, before) or {}
    clean_after = redact(object_type, after) or {}

    changed = {
        key
        for key in clean_before.keys() | clean_after.keys()
        if clean_before.get(key) != clean_after.get(key)
    }
    if not changed:
        return None, None
    return (
        {k: v for k, v in clean_before.items() if k in changed} or None,
        {k: v for k, v in clean_after.items() if k in changed} or None,
    )
