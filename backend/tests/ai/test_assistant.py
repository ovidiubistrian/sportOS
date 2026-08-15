"""The writing assistant.

No test here calls Anthropic. Two reasons: a test that spends money on every
run gets disabled, and a live model gives a different answer each time, so the
only assertions it could support are the weak ones. What is worth testing is
everything around the call — the gate, the meter, the prompt, and what happens
to a response we did not expect — and all of that is deterministic.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text

from app.ai.prompts import BLOCK_SCHEMA, HEADLINE_SCHEMA, polish_system_prompt, render_draft
from app.ai.service import MAX_BLOCKS_PER_REQUEST, WritingAssistant
from app.billing.service import invalidate_entitlements
from app.cms.article_types import BY_KEY, TYPES, get_type
from app.cms.blocks import validate_body
from app.core.config import settings
from app.core.errors import ValidationFailed
from app.platform.ai_router import TenantPolicy

pytestmark = pytest.mark.ai

DRAFT = [
    {"type": "paragraph", "text": "Am pierdut 2-1 la Cluj sâmbătă."},
    {"type": "quote", "text": "Băieții au muncit.", "attribution": "Antrenorul"},
]


class TestArticleTypes:
    def test_every_type_is_usable(self) -> None:
        for spec in TYPES:
            assert spec.name and spec.description, f"{spec.key} is not presentable"
            assert spec.assistant_guidance, (
                f"{spec.key} has no guidance, so 'polish this' would be no better "
                f"than a generic instruction — which is the whole point of types."
            )

    def test_every_skeleton_is_a_valid_body(self) -> None:
        """The starter structure must be storable, or 'new article' 500s."""
        for spec in TYPES:
            assert validate_body(list(spec.skeleton)), f"{spec.key} has an empty skeleton"

    def test_the_types_that_can_cause_a_correction_protect_their_facts(self) -> None:
        for key in ("SIGNING", "DEPARTURE", "MATCH_REPORT"):
            assert BY_KEY[key].protected_facts, (
                f"{key} carries numbers a club would have to publicly correct."
            )

    def test_an_unknown_type_falls_back_rather_than_raising(self) -> None:
        # Called with whatever is on an old row; a 500 on a legacy value would
        # be a worse outcome than treating it as a plain announcement.
        assert get_type("SOMETHING_ELSE").key == "ANNOUNCEMENT"
        assert get_type(None).key == "ANNOUNCEMENT"


class TestPrompt:
    def test_the_first_rule_is_the_one_that_matters(self) -> None:
        prompt = polish_system_prompt(BY_KEY["SIGNING"], "ro")
        assert "Never introduce a fact that is not in the draft" in prompt

    def test_protected_facts_reach_the_prompt(self) -> None:
        prompt = polish_system_prompt(BY_KEY["DEPARTURE"], "ro")
        for fact in BY_KEY["DEPARTURE"].protected_facts:
            assert fact in prompt, f"{fact!r} is declared protected but never stated"

    def test_the_draft_language_is_stated(self) -> None:
        assert "(ro)" in polish_system_prompt(BY_KEY["ANNOUNCEMENT"], "ro")
        assert "Do not translate" in polish_system_prompt(BY_KEY["ANNOUNCEMENT"], "ro")

    def test_quotes_are_rendered_with_their_attribution(self) -> None:
        rendered = render_draft("Înfrângere la Cluj", DRAFT)
        assert "Înfrângere la Cluj" in rendered
        assert "Antrenorul" in rendered, (
            "an unattributed quote invites the model to reassign it"
        )

    def test_the_output_schema_admits_only_blocks_we_render(self) -> None:
        variants = BLOCK_SCHEMA["properties"]["blocks"]["items"]["anyOf"]
        kinds = {v["properties"]["type"]["const"] for v in variants}
        assert kinds == {"paragraph", "heading", "quote", "list"}
        for variant in variants:
            assert variant["additionalProperties"] is False, (
                "an open schema lets the model return a field we would then store"
            )

    def test_the_headline_schema_is_bounded(self) -> None:
        headlines = HEADLINE_SCHEMA["properties"]["headlines"]
        assert headlines["maxItems"] <= 5


class TestDraftBounds:
    """Guards on what we are willing to send, before any money is spent."""

    def test_an_empty_draft_is_refused_locally(self) -> None:
        with pytest.raises(ValidationFailed):
            WritingAssistant._validate_draft("Titlu", [])

    def test_an_oversized_draft_is_refused_locally(self) -> None:
        blocks = [{"type": "paragraph", "text": "x"}] * (MAX_BLOCKS_PER_REQUEST + 1)
        with pytest.raises(ValidationFailed):
            WritingAssistant._validate_draft("Titlu", blocks)

    def test_a_long_body_within_the_block_count_is_still_refused(self) -> None:
        blocks = [{"type": "paragraph", "text": "x" * 4000} for _ in range(10)]
        with pytest.raises(ValidationFailed):
            WritingAssistant._validate_draft("Titlu", blocks)


class TestGate:
    """The assistant costs the platform money, so it is entitlement-gated."""

    async def test_status_tells_the_editor_why_it_is_unavailable(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get("/api/v1/ai/assistant", headers=as_user("owner"))
        assert response.status_code == 200, response.text
        body = response.json()

        assert isinstance(body["available"], bool)
        assert body["requests_used"] >= 0
        # The editor needs a sentence to show, not a silent missing button.
        if not body["available"]:
            assert body["reason"], "unavailable without a reason is an unexplained dead end"
        assert {t["key"] for t in body["article_types"]} == set(BY_KEY)

    async def test_polish_is_closed_by_default(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """`ai_assist` is off in the catalogue, so an ungranted tenant gets 402.

        Failing closed matters more here than elsewhere: an open default would
        bill the platform for every tenant that never bought the feature.
        """
        response = await client.post(
            "/api/v1/ai/polish",
            headers=as_user("owner"),
            json={"locale": "ro", "title": "Înfrângere la Cluj", "blocks": DRAFT},
        )
        assert response.status_code in (402, 409, 503), response.text
        if response.status_code == 402:
            assert response.json()["code"] == "FEATURE_NOT_ENABLED"

    async def test_a_coach_cannot_use_the_assistant(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.post(
            "/api/v1/ai/headlines",
            headers=as_user("coach"),
            json={"locale": "ro", "title": "Titlu", "blocks": DRAFT},
        )
        assert response.status_code in (402, 403)

    async def test_skeletons_are_served_to_editors(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get(
            "/api/v1/ai/article-types/departure/skeleton", headers=as_user("owner")
        )
        assert response.status_code == 200, response.text
        assert response.json()["key"] == "DEPARTURE"
        assert response.json()["skeleton"]

    async def test_an_unknown_skeleton_is_a_422(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get(
            "/api/v1/ai/article-types/nonsense/skeleton", headers=as_user("owner")
        )
        assert response.status_code == 422


class TestPlatformControl:
    """One key, held by the platform; per-tenant policy, set by the super admin."""

    async def test_the_key_is_never_returned(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get("/api/v1/platform/ai", headers=as_user("platform"))
        assert response.status_code == 200, response.text
        body = response.json()

        assert isinstance(body["key_configured"], bool), (
            "the console reports whether a key exists, never the key itself"
        )
        assert "api_key" not in response.text
        key = settings.anthropic_api_key.get_secret_value()
        assert not key or key not in response.text
        assert body["model"] == settings.ai_model
        assert body["tenants"], "every tenant appears, including those with no usage"

    async def test_a_tenant_admin_cannot_see_platform_usage(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get("/api/v1/platform/ai", headers=as_user("owner"))
        assert response.status_code == 403, (
            "a tenant owner must not see what other tenants spend"
        )

    async def test_switching_it_on_requires_a_second_factor(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """`platform.tenant.manage` is a sensitive permission.

        Granting a tenant access to a key the platform pays for is exactly the
        kind of action a stolen session should not be able to perform, so it
        demands step-up authentication. The test tokens come from a password
        grant with no MFA, which is what makes this assertable at all.
        """
        response = await client.put(
            f"/api/v1/platform/ai/tenants/{demo['tenant_id']}",
            headers=as_user("platform"),
            json={"enabled": True, "monthly_limit": 25, "reason": "pytest"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "STEP_UP_REQUIRED"

    def test_a_reason_is_always_required(self) -> None:
        """'Why does this tenant have it?' must always have an answer."""
        with pytest.raises(PydanticValidationError):
            TenantPolicy(enabled=True, monthly_limit=10)

    async def test_a_granted_tenant_sees_its_allowance_immediately(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], admin_engine: Any
    ) -> None:
        """The tenant-visible half of the same mechanism.

        Written against the override table directly because the write endpoint
        needs a step-up token the fixtures cannot mint. What is being proved is
        the part that would otherwise fail silently: the grant reaches the
        tenant at once, rather than after the entitlement cache expires.
        """
        tenant_id = UUID(demo["tenant_id"])
        try:
            async with admin_engine.begin() as conn:
                for feature, limit_value in (
                    ("ai_assist", None),
                    ("ai_requests_per_month", 25),
                ):
                    await conn.execute(
                        text(
                            "INSERT INTO entitlement (id, tenant_id, feature_key, source, "
                            "enabled, limit_value, created_at, updated_at) VALUES "
                            "(gen_random_uuid(), :t, :f, 'OVERRIDE', true, :l, now(), now())"
                        ),
                        {"t": str(tenant_id), "f": feature, "l": limit_value},
                    )
            await invalidate_entitlements(tenant_id)

            status = await client.get("/api/v1/ai/assistant", headers=as_user("owner"))
            assert status.status_code == 200, status.text
            assert status.json()["requests_limit"] == 25
        finally:
            async with admin_engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM entitlement WHERE tenant_id = :t "
                        "AND feature_key IN ('ai_assist', 'ai_requests_per_month')"
                    ),
                    {"t": str(tenant_id)},
                )
            await invalidate_entitlements(tenant_id)
