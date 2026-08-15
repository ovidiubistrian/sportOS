"""Feature and plan reference data.

Plans are data, not code. These are the shipped defaults; the values are
illustrative and are expected to be edited by whoever owns pricing without an
engineer being involved. Nothing in the application reads a plan key.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select

from app.billing.features import CATALOGUE, Feature
from app.billing.models import FeatureRecord, Plan, PlanFeature, PlanPrice, PlanVersion
from app.core.db import platform_session
from app.core.logging import configure_logging
from app.core.model_registry import *  # noqa: F403

log = structlog.get_logger("seed.plans")

F = Feature

# key -> (name, tier, sort, {feature: enabled | limit}, {currency: (month, year)})
PlanSpec = tuple[str, str, int, dict[Feature, bool | int | None], dict[str, tuple[int, int]]]

PLANS: dict[str, PlanSpec] = {
    "STARTER": (
        "Starter",
        "STARTER",
        10,
        {
            F.ACADEMY: True, F.CMS: True,
            F.MAX_CLUBS: 1, F.MAX_TEAMS: 4, F.MAX_PLAYERS: 120,
            F.MAX_STAFF_USERS: 10, F.MAX_VENUES: 1,
            F.EMAILS_PER_MONTH: 2_000, F.STORAGE_GB: 5,
        },
        {"EUR": (4_900, 49_000)},
    ),
    "CLUB": (
        "Club",
        "CLUB",
        20,
        {
            F.ACADEMY: True, F.CMS: True, F.CUSTOM_DOMAIN: True,
            F.TICKETING: True, F.MEMBERSHIPS: True, F.SEASON_TICKETS: True,
            F.SHOP: True, F.FUNDRAISING: True, F.SPONSORSHIP: True,
            F.AI_ASSIST: True,
            F.MAX_CLUBS: 1, F.MAX_TEAMS: 20, F.MAX_PLAYERS: 600,
            F.MAX_STAFF_USERS: 40, F.MAX_VENUES: 2,
            F.EMAILS_PER_MONTH: 20_000, F.STORAGE_GB: 50,
            # The platform pays for these on one key, so every plan states a
            # number. "Unlimited" is a decision for a contract, not a default.
            F.AI_REQUESTS_PER_MONTH: 100,
        },
        {"EUR": (14_900, 149_000)},
    ),
    "PRO": (
        "Pro",
        "PRO",
        30,
        {
            F.ACADEMY: True, F.CMS: True, F.CUSTOM_DOMAIN: True,
            F.TICKETING: True, F.TICKETING_SEATED: True, F.MEMBERSHIPS: True,
            F.SEASON_TICKETS: True, F.SHOP: True, F.FUNDRAISING: True,
            F.SPONSORSHIP: True, F.LOYALTY: True, F.RESALE: True,
            F.WALLET_PASSES: True, F.MEDICAL: True, F.SCOUTING: True,
            F.TRAINING_ADVANCED: True, F.ANALYTICS_ADVANCED: True, F.API_ACCESS: True,
            F.AI_ASSIST: True,
            F.MAX_CLUBS: 3, F.MAX_TEAMS: None, F.MAX_PLAYERS: None,
            F.MAX_STAFF_USERS: 150, F.MAX_VENUES: 5,
            F.EMAILS_PER_MONTH: 100_000, F.SMS_PER_MONTH: 5_000, F.STORAGE_GB: 250,
            F.AI_REQUESTS_PER_MONTH: 500,
        },
        {"EUR": (39_900, 399_000)},
    ),
    "ENTERPRISE": (
        "Enterprise",
        "ENTERPRISE",
        40,
        {
            **{f.key: True for f in CATALOGUE if f.kind.value == "BOOLEAN"},
            F.MAX_CLUBS: None, F.MAX_TEAMS: None, F.MAX_PLAYERS: None,
            F.MAX_STAFF_USERS: None, F.MAX_VENUES: None,
            F.EMAILS_PER_MONTH: None, F.SMS_PER_MONTH: None, F.STORAGE_GB: None,
            F.AI_REQUESTS_PER_MONTH: 2_000,
        },
        {},  # priced per contract
    ),
}


async def seed_plans() -> None:
    async with platform_session(reason="seed plans and features", routine=True) as session:
        existing_features = {row.key for row in await session.scalars(select(FeatureRecord))}
        for spec in CATALOGUE:
            if spec.key.value in existing_features:
                record = await session.get(FeatureRecord, spec.key.value)
                assert record is not None
                record.kind = spec.kind.value
                record.module = spec.module
                record.name = spec.name
                record.default_enabled = spec.default_enabled
                record.default_limit = spec.default_limit
            else:
                session.add(
                    FeatureRecord(
                        key=spec.key.value,
                        kind=spec.kind.value,
                        module=spec.module,
                        name=spec.name,
                        default_enabled=spec.default_enabled,
                        default_limit=spec.default_limit,
                    )
                )
        await session.flush()

        for key, (name, tier, order, features, prices) in PLANS.items():
            plan = await session.scalar(select(Plan).where(Plan.key == key))
            if plan is None:
                plan = Plan(key=key, name=name, tier=tier, sort_order=order)
                session.add(plan)
                await session.flush()

            version = await session.scalar(
                select(PlanVersion).where(
                    PlanVersion.plan_id == plan.id, PlanVersion.version == 1
                )
            )
            if version is None:
                version = PlanVersion(
                    plan_id=plan.id, version=1, effective_from=datetime.now(UTC)
                )
                session.add(version)
                await session.flush()

            # A plan version is meant to be immutable once customers are on it.
            # Rewriting version 1 is safe only while seeding; a real pricing
            # change creates version 2 instead.
            await session.execute(
                delete(PlanFeature).where(PlanFeature.plan_version_id == version.id)
            )
            for feature, value in features.items():
                session.add(
                    PlanFeature(
                        plan_version_id=version.id,
                        feature_key=feature.value,
                        enabled=value is not False,
                        limit_value=(
                            value
                            if isinstance(value, int) and not isinstance(value, bool)
                            else None
                        ),
                    )
                )

            for currency, (monthly, yearly) in prices.items():
                for interval, amount in (("MONTH", monthly), ("YEAR", yearly)):
                    exists = await session.scalar(
                        select(PlanPrice).where(
                            PlanPrice.plan_version_id == version.id,
                            PlanPrice.currency == currency,
                            PlanPrice.interval == interval,
                        )
                    )
                    if exists is None:
                        session.add(
                            PlanPrice(
                                plan_version_id=version.id,
                                currency=currency,
                                interval=interval,
                                amount_minor=amount,
                            )
                        )

        log.info("plans_seeded", features=len(CATALOGUE), plans=len(PLANS))


if __name__ == "__main__":
    configure_logging()
    asyncio.run(seed_plans())
