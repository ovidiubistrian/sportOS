"""Uploads, and what happens when a file is not what it says it is.

The interesting cases here are all adversarial. A club uploading its crest is
the easy path; the ones worth a test are the file that claims to be a PNG and
is not, the image sized to exhaust memory on decode, and the object that must
not be reachable from another tenant.
"""

from __future__ import annotations

import io
from typing import Any

import httpx
import pytest
from PIL import Image

from app.core.errors import ValidationFailed
from app.media.service import MAX_BYTES, inspect

pytestmark = pytest.mark.media


def png(width: int = 240, height: int = 240) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (31, 75, 153)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestInspection:
    """The bytes decide, not the filename and not the Content-Type."""

    def test_a_real_png_is_accepted(self) -> None:
        result = inspect(png())
        assert result.format == "PNG"
        assert result.extension == "png"
        assert (result.width, result.height) == (240, 240)

    def test_a_script_named_as_an_image_is_refused(self) -> None:
        with pytest.raises(ValidationFailed):
            inspect(b"<script>alert(1)</script>")

    def test_an_svg_is_refused(self) -> None:
        """An SVG is a document, not a picture — it can carry script."""
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        with pytest.raises(ValidationFailed):
            inspect(svg)

    def test_an_empty_file_is_refused(self) -> None:
        with pytest.raises(ValidationFailed):
            inspect(b"")

    def test_an_oversized_file_is_refused_before_decoding(self) -> None:
        with pytest.raises(ValidationFailed, match="larger than"):
            inspect(b"\x89PNG\r\n\x1a\n" + b"0" * MAX_BYTES)

    def test_a_truncated_image_is_refused(self) -> None:
        data = png()
        with pytest.raises(ValidationFailed):
            inspect(data[: len(data) // 2])

    def test_a_tiny_image_is_refused(self) -> None:
        with pytest.raises(ValidationFailed, match="too small"):
            inspect(png(8, 8))


class TestUploadRoute:
    async def test_upload_list_and_delete(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        club_id = demo["club_id"]
        created = await client.post(
            "/api/v1/media",
            headers=as_user("owner"),
            data={"club_id": club_id, "purpose": "CREST", "alt_text": "Club crest"},
            files={"file": ("crest.png", png(), "image/png")},
        )
        assert created.status_code == 201, created.text
        asset = created.json()
        assert asset["width"] == 240
        assert asset["alt_text"] == "Club crest"
        # The uploader's filename is a label, never an address.
        assert "crest.png" not in asset["url"]
        assert asset["url"].startswith("http")

        listed = await client.get(
            "/api/v1/media",
            headers=as_user("owner"),
            params={"club_id": club_id, "purpose": "CREST"},
        )
        assert listed.status_code == 200
        assert any(item["id"] == asset["id"] for item in listed.json())

        removed = await client.delete(f"/api/v1/media/{asset['id']}", headers=as_user("owner"))
        assert removed.status_code == 204

    async def test_a_disguised_file_is_a_422(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.post(
            "/api/v1/media",
            headers=as_user("owner"),
            data={"club_id": demo["club_id"], "purpose": "CREST"},
            files={"file": ("crest.png", b"not an image at all", "image/png")},
        )
        assert response.status_code == 422, "the declared content type must count for nothing"

    async def test_an_unknown_purpose_is_rejected(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.post(
            "/api/v1/media",
            headers=as_user("owner"),
            data={"club_id": demo["club_id"], "purpose": "PASSPORT_SCAN"},
            files={"file": ("x.png", png(), "image/png")},
        )
        assert response.status_code == 422

    async def test_a_coach_cannot_upload(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.post(
            "/api/v1/media",
            headers=as_user("coach"),
            data={"club_id": demo["club_id"], "purpose": "CREST"},
            files={"file": ("x.png", png(), "image/png")},
        )
        assert response.status_code == 403

    async def test_another_tenants_asset_is_a_404(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        created = await client.post(
            "/api/v1/media",
            headers=as_user("owner"),
            data={"club_id": demo["club_id"], "purpose": "PARTNER_LOGO"},
            files={"file": ("logo.png", png(), "image/png")},
        )
        asset_id = created.json()["id"]
        try:
            probe = await client.delete(
                f"/api/v1/media/{asset_id}", headers=as_user("other_owner")
            )
            assert probe.status_code == 404
        finally:
            await client.delete(f"/api/v1/media/{asset_id}", headers=as_user("owner"))
