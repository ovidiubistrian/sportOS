"""The editorial workflow, end to end.

One article is taken from draft to published to archived, in two languages,
with the access rules asserted along the way. Written as a sequence because
that is how the workflow is actually used — a per-endpoint matrix would test
five isolated calls and never notice that publishing an untranslated article
is possible.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from PIL import Image

pytestmark = pytest.mark.cms


def png(width: int = 240, height: int = 240) -> bytes:
    """A real image, because the uploader inspects the bytes and not the name."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (31, 75, 153)).save(buffer, format="PNG")
    return buffer.getvalue()


RO_BODY = [
    {"type": "paragraph", "text": "Clubul anunță transferul lui Andrei Pop de la FC Vecin."},
    {"type": "quote", "text": "Sunt fericit să fiu aici.", "attribution": "Andrei Pop"},
]


def _article(club_id: str, suffix: str) -> dict[str, Any]:
    return {
        "club_id": club_id,
        "article_type": "SIGNING",
        "translation": {
            "locale": "ro",
            "title": f"Un nou transfer {suffix}",
            "body": RO_BODY,
            "excerpt": "Andrei Pop semnează.",
        },
    }


class TestEditorialWorkflow:
    async def test_draft_to_published_to_archived(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        created = await client.post(
            "/api/v1/content", headers=as_user("owner"), json=_article(demo["club_id"], "A")
        )
        assert created.status_code == 201, created.text
        item = created.json()
        item_id = item["id"]

        assert item["status"] == "DRAFT"
        assert item["article_type"] == "SIGNING"
        assert item["published_at"] is None
        assert [t["locale"] for t in item["translations"]] == ["ro"]
        # The slug is derived from the title, diacritics folded, not transliterated
        # away into something unreadable.
        assert item["translations"][0]["slug"].startswith("un-nou-transfer")

        # A second language. The item is one article; the words are per locale.
        translated = await client.put(
            f"/api/v1/content/{item_id}/translations/en",
            headers=as_user("owner"),
            json={
                "locale": "en",
                "title": "A new signing A",
                "body": [{"type": "paragraph", "text": "The club signs Andrei Pop."}],
                "status": "READY",
            },
        )
        assert translated.status_code == 200, translated.text
        locales = {t["locale"]: t for t in translated.json()["translations"]}
        assert set(locales) == {"ro", "en"}
        assert all(loc["is_complete"] for loc in translated.json()["locales"])

        published = await client.post(
            f"/api/v1/content/{item_id}/status",
            headers=as_user("owner"),
            json={"status": "PUBLISHED"},
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "PUBLISHED"
        assert published.json()["published_at"] is not None

        archived = await client.post(
            f"/api/v1/content/{item_id}/status",
            headers=as_user("owner"),
            json={"status": "ARCHIVED"},
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "ARCHIVED"

        await client.delete(f"/api/v1/content/{item_id}", headers=as_user("owner"))

    async def test_scheduling_requires_a_date(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        created = await client.post(
            "/api/v1/content", headers=as_user("owner"), json=_article(demo["club_id"], "B")
        )
        item_id = created.json()["id"]

        missing = await client.post(
            f"/api/v1/content/{item_id}/status",
            headers=as_user("owner"),
            json={"status": "SCHEDULED"},
        )
        assert missing.status_code == 422, (
            "A scheduled article without a date would never publish."
        )

        when = datetime.now(UTC) + timedelta(days=2)
        scheduled = await client.post(
            f"/api/v1/content/{item_id}/status",
            headers=as_user("owner"),
            json={"status": "SCHEDULED", "scheduled_for": when.isoformat()},
        )
        assert scheduled.status_code == 200, scheduled.text
        assert scheduled.json()["scheduled_for"] is not None

        await client.delete(f"/api/v1/content/{item_id}", headers=as_user("owner"))

    async def test_an_unknown_article_type_is_rejected(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        payload = _article(demo["club_id"], "C")
        payload["article_type"] = "TRANSFER_RUMOUR"
        response = await client.post("/api/v1/content", headers=as_user("owner"), json=payload)
        assert response.status_code == 422

    async def test_a_script_tag_survives_only_as_text(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """Blocks carry text, so markup cannot become markup."""
        payload = _article(demo["club_id"], "D")
        payload["translation"]["body"] = [
            {"type": "paragraph", "text": "<script>alert(1)</script>"}
        ]
        created = await client.post("/api/v1/content", headers=as_user("owner"), json=payload)
        assert created.status_code == 201
        stored = created.json()["translations"][0]["body"][0]
        assert stored["type"] == "paragraph"
        assert stored["text"] == "<script>alert(1)</script>"
        assert set(stored) == {"type", "text"}, "a block carries text, and nothing else"

        await client.delete(f"/api/v1/content/{created.json()['id']}", headers=as_user("owner"))


class TestAccess:
    async def test_a_coach_cannot_reach_the_newsroom(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get("/api/v1/content", headers=as_user("coach"))
        assert response.status_code == 403

    async def test_another_tenants_article_is_a_404(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        created = await client.post(
            "/api/v1/content", headers=as_user("owner"), json=_article(demo["club_id"], "E")
        )
        item_id = created.json()["id"]
        try:
            probe = await client.get(
                f"/api/v1/content/{item_id}", headers=as_user("other_owner")
            )
            assert probe.status_code == 404, (
                "403 would confirm the article exists, which is the leak."
            )
        finally:
            await client.delete(f"/api/v1/content/{item_id}", headers=as_user("owner"))

    async def test_drafts_are_not_public(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        created = await client.post(
            "/api/v1/content", headers=as_user("owner"), json=_article(demo["club_id"], "F")
        )
        item = created.json()
        slug = item["translations"][0]["slug"]
        try:
            public = await client.get(
                f"/api/v1/public/news/{slug}?locale=ro",
                headers={"X-Forwarded-Host": "fcexample.localhost"},
            )
            assert public.status_code == 404, "an unpublished draft must not be readable"
        finally:
            await client.delete(f"/api/v1/content/{item['id']}", headers=as_user("owner"))


class TestCoverAtCreation:
    """The picture is chosen while the article is written, not after it exists.

    The editor used to defer the cover until the first save, on the reasoning
    that a new article has no id for an image to attach to. It does not need
    one: the image is uploaded to the club's media library, and the article
    only names it. `POST /content` has always accepted `cover_media_id` — what
    it did not do was check it, which the update path had done all along.
    """

    async def test_an_article_is_created_with_its_cover(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        uploaded = await client.post(
            "/api/v1/media",
            headers=as_user("owner"),
            data={
                "club_id": demo["club_id"],
                "purpose": "ARTICLE_IMAGE",
                "alt_text": "Andrei Pop semnează",
            },
            files={"file": ("signing.png", png(), "image/png")},
        )
        assert uploaded.status_code == 201, uploaded.text
        asset = uploaded.json()

        payload = _article(demo["club_id"], "G") | {"cover_media_id": asset["id"]}
        created = await client.post("/api/v1/content", headers=as_user("owner"), json=payload)
        assert created.status_code == 201, created.text
        item = created.json()
        try:
            assert item["cover_media_id"] == asset["id"]
            # The URL too: the id round-tripping proves it was stored, and the
            # URL proves the article can actually show the picture.
            assert item["cover_url"]
        finally:
            await client.delete(f"/api/v1/content/{item['id']}", headers=as_user("owner"))
            await client.delete(f"/api/v1/media/{asset['id']}", headers=as_user("owner"))

    async def test_a_cover_that_does_not_exist_is_refused(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """Refused outright rather than stored and silently rendering nothing."""
        payload = _article(demo["club_id"], "H") | {"cover_media_id": str(uuid4())}
        created = await client.post("/api/v1/content", headers=as_user("owner"), json=payload)
        assert created.status_code == 404, created.text

    async def test_another_tenants_picture_is_not_a_cover(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """The id is real, and still refused: it belongs to somebody else."""
        theirs = (await client.get("/api/v1/me", headers=as_user("other_owner"))).json()
        their_club = theirs["clubs"][0]["id"]

        uploaded = await client.post(
            "/api/v1/media",
            headers=as_user("other_owner"),
            data={"club_id": their_club, "purpose": "ARTICLE_IMAGE"},
            files={"file": ("theirs.png", png(), "image/png")},
        )
        assert uploaded.status_code == 201, uploaded.text
        asset = uploaded.json()

        try:
            payload = _article(demo["club_id"], "I") | {"cover_media_id": asset["id"]}
            created = await client.post(
                "/api/v1/content", headers=as_user("owner"), json=payload
            )
            assert created.status_code == 404, created.text
        finally:
            await client.delete(f"/api/v1/media/{asset['id']}", headers=as_user("other_owner"))
