"""What a country implies.

A club signing up tells us where it is, and that answers two questions it should
not have to be asked separately: what currency it prices in, and what language
it most likely speaks. Both are defaults, both are changeable in settings — the
point is that a Romanian club is not asked to confirm that it uses lei.

Open by design, unlike the locale list. A country we have no entry for still
works: it falls back to EUR and English, which is wrong but harmless and
correctable, whereas refusing the sign-up would not be. The map grows as clubs
arrive, and adding a row is one line.
"""

from __future__ import annotations

from dataclasses import dataclass

FALLBACK_CURRENCY = "EUR"
FALLBACK_LOCALE = "en"


@dataclass(frozen=True, slots=True)
class Country:
    code: str
    currency: str
    # The locale to default the interface to, if the platform ships it. A code
    # we do not support falls back — see `locale_for`.
    locale: str


COUNTRIES: tuple[Country, ...] = (
    Country("RO", "RON", "ro"),
    Country("MD", "MDL", "ro"),
    Country("GB", "GBP", "en"),
    Country("IE", "EUR", "en"),
    Country("US", "USD", "en"),
    Country("DE", "EUR", "de"),
    Country("FR", "EUR", "fr"),
    Country("ES", "EUR", "es"),
    Country("IT", "EUR", "it"),
    Country("PT", "EUR", "pt"),
    Country("NL", "EUR", "nl"),
    Country("BE", "EUR", "nl"),
    Country("AT", "EUR", "de"),
    Country("PL", "PLN", "pl"),
    Country("HU", "HUF", "hu"),
    Country("CZ", "CZK", "cs"),
    Country("BG", "BGN", "bg"),
    Country("RS", "RSD", "sr"),
    Country("HR", "EUR", "hr"),
    Country("GR", "EUR", "el"),
    Country("TR", "TRY", "tr"),
    Country("CH", "CHF", "de"),
    Country("SE", "SEK", "sv"),
    Country("NO", "NOK", "no"),
    Country("DK", "DKK", "da"),
)

BY_CODE = {country.code: country for country in COUNTRIES}


def currency_for(country_code: str | None) -> str:
    country = BY_CODE.get((country_code or "").upper())
    return country.currency if country else FALLBACK_CURRENCY


def locale_for(country_code: str | None, supported: frozenset[str]) -> str:
    """The interface language to start a club in.

    Checked against what the platform actually ships: a German club gets the
    German interface the day it exists, and English until then — never a half
    of an interface in a language nobody translated.
    """
    country = BY_CODE.get((country_code or "").upper())
    if country and country.locale in supported:
        return country.locale
    return FALLBACK_LOCALE
