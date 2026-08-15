"""Entitlements gate real behaviour, not just the UI."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.billing.features import CATALOGUE, Feature, FeatureKind, get_feature
from app.billing.service import Entitlements, FeatureState
from app.core.errors import FeatureNotEnabled, LimitExceeded

pytestmark = pytest.mark.entitlements


class TestCatalogue:
    def test_feature_keys_are_unique(self) -> None:
        keys = [spec.key.value for spec in CATALOGUE]
        assert len(keys) == len(set(keys))

    def test_unknown_feature_fails_loudly(self) -> None:
        with pytest.raises(KeyError, match="Unknown feature"):
            get_feature("not_a_feature")

    def test_revenue_features_are_closed_by_default(self) -> None:
        """A feature nobody has configured must not be free."""
        for key in (Feature.TICKETING, Feature.SHOP, Feature.LOYALTY, Feature.RESALE):
            assert get_feature(key).default_enabled is False

    def test_limits_have_a_default(self) -> None:
        for spec in CATALOGUE:
            if spec.kind is FeatureKind.LIMIT:
                assert spec.default_limit is not None, f"{spec.key} has no default limit"


class TestResolution:
    def test_unknown_feature_falls_back_to_the_catalogue_default(self) -> None:
        entitlements = Entitlements(features={})
        assert entitlements.enabled(Feature.ACADEMY) is True
        assert entitlements.enabled(Feature.RESALE) is False

    def test_require_raises_with_the_feature_in_the_details(self) -> None:
        entitlements = Entitlements(features={Feature.SHOP.value: FeatureState(False, None)})
        with pytest.raises(FeatureNotEnabled) as excinfo:
            entitlements.require(Feature.SHOP)
        assert excinfo.value.details["feature"] == "shop"
        assert excinfo.value.status == 402

    def test_limit_of_none_means_unlimited(self) -> None:
        entitlements = Entitlements(
            features={Feature.MAX_TEAMS.value: FeatureState(True, None)}
        )
        entitlements.check_limit(Feature.MAX_TEAMS, current=10_000)  # no raise

    def test_limit_zero_is_not_unlimited(self) -> None:
        """0 and NULL are different, and confusing them gives away the product."""
        entitlements = Entitlements(features={Feature.MAX_TEAMS.value: FeatureState(True, 0)})
        with pytest.raises(LimitExceeded):
            entitlements.check_limit(Feature.MAX_TEAMS, current=0)

    def test_limit_boundary(self) -> None:
        entitlements = Entitlements(features={Feature.MAX_TEAMS.value: FeatureState(True, 4)})
        entitlements.check_limit(Feature.MAX_TEAMS, current=3)  # the 4th is allowed
        with pytest.raises(LimitExceeded) as excinfo:
            entitlements.check_limit(Feature.MAX_TEAMS, current=4)
        assert excinfo.value.details["limit"] == 4
        assert excinfo.value.details["current"] == 4


class TestPlanDrivenAccess:
    async def test_demo_tenants_are_on_different_plans(self, admin_engine: AsyncEngine) -> None:
        async with admin_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT t.slug, p.key FROM tenant_subscription s "
                        "JOIN tenant t ON t.id = s.tenant_id "
                        "JOIN plan_version v ON v.id = s.plan_version_id "
                        "JOIN plan p ON p.id = v.plan_id "
                        "WHERE t.is_demo ORDER BY t.slug"
                    )
                )
            ).all()
        plans = dict(rows)
        assert plans.get("fc-example") == "PRO"
        assert plans.get("northern-united") == "STARTER"

    async def test_academy_gated_route_works_when_entitled(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        for user in ("owner", "other_owner"):
            response = await client.get("/api/v1/players?limit=1", headers=as_user(user))
            assert response.status_code == 200, (
                f"{user} should have the academy feature on their plan"
            )

    async def test_disabling_a_feature_closes_the_route(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        admin_engine: AsyncEngine,
    ) -> None:
        """The decisive test: an override turns a working endpoint into a 402."""
        from app.billing.service import EntitlementService
        from app.core.db import SessionFactory

        tenant_id = UUID(demo["tenant_id"])

        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO entitlement "
                    "(id, tenant_id, feature_key, source, enabled, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :t, 'academy', 'OVERRIDE', false, now(), now())"
                ),
                {"t": str(tenant_id)},
            )
        async with SessionFactory() as session:
            await EntitlementService(session).invalidate(tenant_id)

        try:
            blocked = await client.get("/api/v1/players?limit=1", headers=as_user("owner"))
            assert blocked.status_code == 402, (
                f"expected 402 with the feature off, got {blocked.status_code}"
            )
            body = blocked.json()
            assert body["code"] == "FEATURE_NOT_ENABLED"
            assert body["details"]["feature"] == "academy"

            # Another tenant is unaffected — entitlements are per tenant.
            other = await client.get("/api/v1/players?limit=1", headers=as_user("other_owner"))
            assert other.status_code == 200
        finally:
            async with admin_engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM entitlement WHERE tenant_id = :t "
                        "AND feature_key = 'academy'"
                    ),
                    {"t": str(tenant_id)},
                )
            async with SessionFactory() as session:
                await EntitlementService(session).invalidate(tenant_id)

        restored = await client.get("/api/v1/players?limit=1", headers=as_user("owner"))
        assert restored.status_code == 200, "removing the override did not restore access"


def test_no_module_branches_on_a_plan_name() -> None:
    """Comparing a plan to a literal is how entitlements stop being configurable.

    Parsed with `ast` rather than grepped, so documentation that *describes* the
    forbidden pattern does not trip the check — and so a comparison written
    across several lines still does.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    offenders: list[str] = []

    for path in root.rglob("*.py"):
        if "seeds" in path.parts:  # seeds legitimately name plans
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            left = node.left
            name = (
                left.attr
                if isinstance(left, ast.Attribute)
                else left.id
                if isinstance(left, ast.Name)
                else ""
            )
            if "plan" not in name.lower():
                continue
            if any(
                isinstance(c, ast.Constant) and isinstance(c.value, str)
                for c in node.comparators
            ):
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")

    assert not offenders, f"These modules branch on a plan instead of a feature: {offenders}"
