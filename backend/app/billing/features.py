"""The feature catalogue.

Business code asks about a feature, never about a plan:

    await entitlements.require(ctx, Feature.TICKETING)   # correct
    if tenant.plan == "PRO": ...                          # forbidden

A plan is a commercial packaging of features and changes whenever sales says
so. If plan names reach domain logic, every pricing experiment becomes an
engineering project. See docs/architecture/07-entitlements.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FeatureKind(StrEnum):
    BOOLEAN = "BOOLEAN"  # a capability is on or off
    LIMIT = "LIMIT"  # a hard ceiling, checked at write time
    QUOTA = "QUOTA"  # metered per period


class Feature(StrEnum):
    # --- modules ---------------------------------------------------------
    ACADEMY = "academy"
    TRAINING_ADVANCED = "training_advanced"
    SCOUTING = "scouting"
    MEDICAL = "medical"
    CMS = "cms"
    TICKETING = "ticketing"
    TICKETING_SEATED = "ticketing_seated"
    SEASON_TICKETS = "season_tickets"
    MEMBERSHIPS = "memberships"
    SHOP = "shop"
    FUNDRAISING = "fundraising"
    LOYALTY = "loyalty"
    SPONSORSHIP = "sponsorship"
    RESALE = "resale"
    WALLET_PASSES = "wallet_passes"
    ANALYTICS_ADVANCED = "analytics_advanced"
    CUSTOM_DOMAIN = "custom_domain"
    API_ACCESS = "api_access"
    SSO_ENTERPRISE = "sso_enterprise"
    AI_ASSIST = "ai_assist"

    # --- limits ----------------------------------------------------------
    MAX_CLUBS = "max_clubs"
    MAX_TEAMS = "max_teams"
    MAX_PLAYERS = "max_players"
    MAX_STAFF_USERS = "max_staff_users"
    MAX_VENUES = "max_venues"

    # --- quotas ----------------------------------------------------------
    EMAILS_PER_MONTH = "emails_per_month"
    SMS_PER_MONTH = "sms_per_month"
    STORAGE_GB = "storage_gb"
    AI_REQUESTS_PER_MONTH = "ai_requests_per_month"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    key: Feature
    kind: FeatureKind
    module: str
    name: str
    # What a tenant gets when no plan or override says otherwise. Defaults are
    # deliberately closed for revenue features and open for core ones.
    default_enabled: bool = False
    default_limit: int | None = None


def _boolean(key: Feature, module: str, name: str, *, default: bool = False) -> FeatureSpec:
    return FeatureSpec(key, FeatureKind.BOOLEAN, module, name, default_enabled=default)


def _limit(key: Feature, module: str, name: str, default: int | None) -> FeatureSpec:
    return FeatureSpec(
        key, FeatureKind.LIMIT, module, name, default_enabled=True, default_limit=default
    )


def _quota(key: Feature, module: str, name: str, default: int | None) -> FeatureSpec:
    return FeatureSpec(
        key, FeatureKind.QUOTA, module, name, default_enabled=True, default_limit=default
    )


CATALOGUE: tuple[FeatureSpec, ...] = (
    _boolean(Feature.ACADEMY, "academy", "Academy management", default=True),
    _boolean(Feature.CMS, "cms", "Website and news", default=True),
    _boolean(Feature.TRAINING_ADVANCED, "training", "Periodisation and load planning"),
    _boolean(Feature.SCOUTING, "scouting", "Scouting and prospects"),
    _boolean(Feature.MEDICAL, "medical", "Medical records"),
    _boolean(Feature.TICKETING, "ticketing", "Ticketing"),
    _boolean(Feature.TICKETING_SEATED, "ticketing", "Assigned seating"),
    _boolean(Feature.SEASON_TICKETS, "memberships", "Season tickets"),
    _boolean(Feature.MEMBERSHIPS, "memberships", "Club membership"),
    _boolean(Feature.SHOP, "commerce", "Online shop"),
    _boolean(Feature.FUNDRAISING, "fundraising", "Fundraising campaigns"),
    _boolean(Feature.LOYALTY, "loyalty", "Loyalty programme"),
    _boolean(Feature.SPONSORSHIP, "sponsorship", "Sponsor management"),
    _boolean(Feature.RESALE, "ticketing", "Official resale"),
    _boolean(Feature.WALLET_PASSES, "access_control", "Apple and Google Wallet"),
    _boolean(Feature.ANALYTICS_ADVANCED, "analytics", "Advanced analytics"),
    _boolean(Feature.CUSTOM_DOMAIN, "tenants", "Custom domain"),
    _boolean(Feature.API_ACCESS, "platform", "API access"),
    _boolean(Feature.SSO_ENTERPRISE, "identity", "Enterprise SSO"),
    _boolean(Feature.AI_ASSIST, "ai", "Writing assistant"),
    _limit(Feature.MAX_CLUBS, "clubs", "Clubs", 1),
    _limit(Feature.MAX_TEAMS, "teams", "Teams", 4),
    _limit(Feature.MAX_PLAYERS, "players", "Players", 100),
    _limit(Feature.MAX_STAFF_USERS, "staff", "Staff accounts", 10),
    _limit(Feature.MAX_VENUES, "venues", "Venues", 1),
    _quota(Feature.EMAILS_PER_MONTH, "notifications", "Emails per month", 2_000),
    _quota(Feature.SMS_PER_MONTH, "notifications", "SMS per month", 0),
    _quota(Feature.STORAGE_GB, "media", "Storage (GB)", 5),
    # The platform pays for these on a shared key, so the default is zero:
    # a tenant gets assistant requests only when a plan or override grants them.
    _quota(Feature.AI_REQUESTS_PER_MONTH, "ai", "Assistant requests per month", 0),
)

BY_KEY: dict[str, FeatureSpec] = {spec.key.value: spec for spec in CATALOGUE}

UNLIMITED = None


def get_feature(key: Feature | str) -> FeatureSpec:
    value = key.value if isinstance(key, Feature) else key
    try:
        return BY_KEY[value]
    except KeyError as exc:
        raise KeyError(
            f"Unknown feature {value!r}. Add it to app/billing/features.py so it "
            "is seeded and covered by the entitlement tests."
        ) from exc
