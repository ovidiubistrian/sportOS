"""Public plan catalogue.

Unauthenticated, because a pricing page has to render for someone who has never
signed in. It exposes only what is already on the marketing site: plan names,
public prices and a short highlight list. Never the feature matrix row by row —
that is commercial packaging, it changes constantly, and a competitor reading
it off an endpoint is a self-inflicted wound.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.billing.features import Feature
from app.billing.models import Plan, PlanFeature, PlanPrice, PlanVersion
from app.core.db import platform_session

router = APIRouter(prefix="/public/plans", tags=["public"])

# What a club actually compares plans on. Ordered, and short on purpose: a
# fifteen-line bullet list is read by nobody.
HIGHLIGHT_LIMITS = (
    (Feature.MAX_PLAYERS, "{value} players", "Unlimited players"),
    (Feature.MAX_TEAMS, "{value} teams", "Unlimited teams"),
    (Feature.MAX_STAFF_USERS, "{value} staff accounts", "Unlimited staff accounts"),
)

HIGHLIGHT_MODULES = (
    (Feature.CMS, "Club website and newsroom"),
    (Feature.ACADEMY, "Academy and training"),
    (Feature.TICKETING, "Ticketing"),
    (Feature.MEMBERSHIPS, "Membership"),
    (Feature.SHOP, "Online shop"),
    (Feature.AI_ASSIST, "Writing assistant"),
    (Feature.MEDICAL, "Medical records"),
    (Feature.ANALYTICS_ADVANCED, "Advanced analytics"),
    (Feature.SSO_ENTERPRISE, "Single sign-on"),
)


class PublicPrice(BaseModel):
    currency: str
    amount_monthly: int | None = None
    amount_yearly: int | None = None


class PublicPlan(BaseModel):
    key: str
    name: str
    tier: str
    highlights: list[str]
    prices: list[PublicPrice]


def _highlights(states: dict[str, tuple[bool, int | None]]) -> list[str]:
    lines: list[str] = []

    for feature, template, unlimited in HIGHLIGHT_LIMITS:
        state = states.get(feature.value)
        if state is None:
            continue
        enabled, limit = state
        if not enabled:
            continue
        lines.append(unlimited if limit is None else template.format(value=f"{limit:,}"))

    for feature, label in HIGHLIGHT_MODULES:
        state = states.get(feature.value)
        if state and state[0]:
            lines.append(label)

    return lines[:8]


@router.get("", response_model=list[PublicPlan], summary="Plans shown on the pricing page")
async def public_plans() -> list[PublicPlan]:
    async with platform_session(
        reason="render the public pricing page", routine=True
    ) as session:
        rows = (
            await session.execute(
                select(Plan, PlanVersion)
                .join(PlanVersion, PlanVersion.plan_id == Plan.id)
                .where(Plan.status == "ACTIVE", Plan.is_public.is_(True))
                .order_by(Plan.sort_order, PlanVersion.version.desc())
            )
        ).all()

        # One version per plan: the highest-numbered one is what a new customer
        # would be signing up to today. Existing subscriptions stay pinned to
        # whichever version they bought.
        latest: dict[str, tuple[Plan, PlanVersion]] = {}
        for plan, version in rows:
            latest.setdefault(plan.key, (plan, version))

        plans: list[PublicPlan] = []
        for plan, version in latest.values():
            features = {
                key: (enabled, limit)
                for key, enabled, limit in (
                    await session.execute(
                        select(
                            PlanFeature.feature_key,
                            PlanFeature.enabled,
                            PlanFeature.limit_value,
                        ).where(PlanFeature.plan_version_id == version.id)
                    )
                ).all()
            }
            prices_by_currency: dict[str, PublicPrice] = {}
            for price in await session.scalars(
                select(PlanPrice).where(PlanPrice.plan_version_id == version.id)
            ):
                entry = prices_by_currency.setdefault(
                    price.currency, PublicPrice(currency=price.currency)
                )
                if price.interval == "MONTH":
                    entry.amount_monthly = price.amount_minor
                elif price.interval == "YEAR":
                    entry.amount_yearly = price.amount_minor

            plans.append(
                PublicPlan(
                    key=plan.key,
                    name=plan.name,
                    tier=plan.tier,
                    highlights=_highlights(features),
                    prices=list(prices_by_currency.values()),
                )
            )
        return plans
