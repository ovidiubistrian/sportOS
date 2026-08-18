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
# Only ever reached for a country not in the catalogue. `UTC` as a *default*
# is what produced the bug this constant is documented by: a Romanian club
# whose fixtures all displayed three hours early through the summer, because
# kick-off is stored in UTC and rendered in the club's zone.
FALLBACK_TIMEZONE = "UTC"


@dataclass(frozen=True, slots=True)
class Country:
    code: str
    currency: str
    # The locale to default the interface to, if the platform ships it. A code
    # we do not support falls back — see `locale_for`.
    locale: str
    # An IANA zone, never a fixed offset: the offset changes twice a year and
    # a kick-off time that is right in November and wrong in June is worse
    # than one that is always wrong, because nobody goes looking for it.
    #
    # Countries spanning several zones get their most populous one. It is a
    # starting value a club can correct, not a claim about geography.
    timezone: str


COUNTRIES: tuple[Country, ...] = (
    Country("RO", "RON", "ro", "Europe/Bucharest"),
    Country("MD", "MDL", "ro", "Europe/Chisinau"),
    Country("GB", "GBP", "en", "Europe/London"),
    Country("IE", "EUR", "en", "Europe/Dublin"),
    Country("US", "USD", "en", "America/New_York"),
    Country("DE", "EUR", "de", "Europe/Berlin"),
    Country("FR", "EUR", "fr", "Europe/Paris"),
    Country("ES", "EUR", "es", "Europe/Madrid"),
    Country("IT", "EUR", "it", "Europe/Rome"),
    Country("PT", "EUR", "pt", "Europe/Lisbon"),
    Country("NL", "EUR", "nl", "Europe/Amsterdam"),
    Country("BE", "EUR", "nl", "Europe/Brussels"),
    Country("AT", "EUR", "de", "Europe/Vienna"),
    Country("PL", "PLN", "pl", "Europe/Warsaw"),
    Country("HU", "HUF", "hu", "Europe/Budapest"),
    Country("CZ", "CZK", "cs", "Europe/Prague"),
    Country("BG", "BGN", "bg", "Europe/Sofia"),
    Country("RS", "RSD", "sr", "Europe/Belgrade"),
    Country("HR", "EUR", "hr", "Europe/Zagreb"),
    Country("GR", "EUR", "el", "Europe/Athens"),
    Country("TR", "TRY", "tr", "Europe/Istanbul"),
    Country("CH", "CHF", "de", "Europe/Zurich"),
    Country("SE", "SEK", "sv", "Europe/Stockholm"),
    Country("NO", "NOK", "no", "Europe/Oslo"),
    Country("DK", "DKK", "da", "Europe/Copenhagen"),
)

BY_CODE = {country.code: country for country in COUNTRIES}


def timezone_for(country_code: str | None) -> str:
    """The club's zone, from its country.

    Derived rather than defaulted, for the same reason the currency and the
    locale are: a club signing up in Romania has already said where it is, and
    asking again — or quietly assuming UTC — is how every kick-off on the site
    ends up three hours early.
    """
    country = BY_CODE.get((country_code or "").upper())
    return country.timezone if country else FALLBACK_TIMEZONE


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
