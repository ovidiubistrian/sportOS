"""Supported languages.

One list, used for three different things that must never disagree:

  * the language a tenant's **interface** is in;
  * the languages a club **publishes** in;
  * the locales an article translation may exist for.

Deliberately a closed set. A locale is not free: each one needs a translated
interface, a date and number format that a native reader recognises, and
someone who can check the wording. Letting a tenant type `pt-BR` into a field
produces a half-translated product and a support ticket, so the platform ships
languages it has actually done the work for and grows the list on purpose.

Adding one is three edits and a translation pass: this tuple, the catalogue in
`packages/i18n`, and a migration only if an existing tenant should get it by
default. `tests/tenants/test_locales.py` fails if the catalogues and this list
drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Locale:
    code: str
    # In the language itself, never translated. A speaker looking for their own
    # language scans for the word they use for it, not for the English name.
    endonym: str
    english_name: str


SUPPORTED_LOCALES: tuple[Locale, ...] = (
    Locale("en", "English", "English"),
    Locale("ro", "Română", "Romanian"),
)

LOCALE_CODES: frozenset[str] = frozenset(locale.code for locale in SUPPORTED_LOCALES)

DEFAULT_LOCALE = "en"


def is_supported(code: str) -> bool:
    return code.strip().lower() in LOCALE_CODES


def normalise(code: str) -> str:
    """Fold a browser or client locale onto one we support.

    `ro-RO`, `RO` and `ro` are all Romanian. Region subtags are dropped rather
    than rejected: a request from `en-GB` should get English, not an error.
    """
    base = code.strip().lower().replace("_", "-").split("-")[0]
    return base if base in LOCALE_CODES else DEFAULT_LOCALE


def validate(codes: list[str], *, field: str = "supported_locales") -> list[str]:
    """Check a set of locales, preserving order and removing duplicates."""
    from app.core.errors import ValidationFailed

    seen: list[str] = []
    for code in codes:
        cleaned = code.strip().lower()
        if cleaned not in LOCALE_CODES:
            raise ValidationFailed(
                f"{cleaned!r} is not a language this platform supports yet.",
                field=field,
                supported=sorted(LOCALE_CODES),
            )
        if cleaned not in seen:
            seen.append(cleaned)

    if not seen:
        raise ValidationFailed("A tenant must publish in at least one language.", field=field)
    return seen
