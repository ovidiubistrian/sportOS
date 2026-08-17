"""Building a stadium through the API, exactly as the admin screen does.

The service layer is covered by `test_stadium_to_scan.py`. This covers the
*wire*: the payloads the builder actually sends, against schemas that
`forbid` extra fields. A renamed field or a forgotten default fails here
rather than in front of a club secretary halfway through drawing their ground.

It walks the whole wizard in order — venue, configuration, price zone, stand,
sector, seats, gate, review, publish — because that order is the feature. Each
step needs what the one before it produced, and a test that set them up
independently would not notice if that stopped being true.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.commerce

BASE = "/api/v1/ticketing"


def _box(x: int, y: int, width: int, height: int) -> dict[str, Any]:
    return {
        "points": [
            [x, y],
            [x + width, y],
            [x + width, y + height],
            [x, y + height],
        ]
    }


async def test_the_wizard_builds_a_publishable_ground(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    owner = as_user("owner")
    suffix = uuid4().hex[:6].upper()

    # Step 1 — the ground itself.
    venue = await client.post(
        f"{BASE}/venues",
        headers=owner,
        json={
            "club_id": demo["club_id"],
            "name": f"Test Arena {suffix}",
            "code": f"TA{suffix}",
            "city": "Reșița",
            "address": "Strada Test 1",
            "expected_capacity": 0,
            "pitch_orientation": "NORTH_SOUTH",
        },
    )
    assert venue.status_code == 201, venue.text
    venue_id = venue.json()["id"]

    # Step 2 — a versioned configuration, which starts as a draft.
    config = await client.post(
        f"{BASE}/venues/{venue_id}/configurations",
        headers=owner,
        json={"name": f"Fotbal {suffix}"},
    )
    assert config.status_code == 201, config.text
    body = config.json()
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    configuration_id = body["id"]

    # Step 6, done early — a sector needs a zone before it can be priced.
    zone = await client.post(
        f"{BASE}/configurations/{configuration_id}/price-zones",
        headers=owner,
        json={"name": "Categoria 1", "code": "CAT1", "colour": "#1d4ed8"},
    )
    assert zone.status_code == 201, zone.text
    zone_id = zone.json()["id"]

    # Step 3 — a stand, with geometry chosen from a side rather than drawn.
    stand = await client.post(
        f"{BASE}/configurations/{configuration_id}/stands",
        headers=owner,
        json={
            "name": "Tribuna Principală",
            "code": "TP",
            "display_order": 0,
            "geometry": _box(120, 250, 170, 500),
        },
    )
    assert stand.status_code == 201, stand.text
    stand_id = stand.json()["id"]

    section = await client.post(
        f"{BASE}/stands/{stand_id}/sections",
        headers=owner,
        json={
            "name": "Sector A",
            "code": "TPA",
            "kind": "RESERVED",
            "declared_capacity": 0,
            "price_zone_id": zone_id,
            "display_order": 0,
            "geometry": _box(130, 260, 150, 200),
        },
    )
    assert section.status_code == 201, section.text
    section_id = section.json()["id"]

    # Step 4 — rows and seats, including the accessible bay.
    seats = await client.post(
        f"{BASE}/sections/{section_id}/seats",
        headers=owner,
        json={
            "row_count": 4,
            "seats_per_row": 10,
            "row_start_label": "A",
            "row_label_style": "ALPHABETIC",
            "first_seat_number": 1,
            "direction": "LEFT_TO_RIGHT",
            "wheelchair_seats": ["A:1"],
            "obstructed_seats": ["A:10"],
            "replace": False,
        },
    )
    assert seats.status_code == 200, seats.text
    assert seats.json()["seats"] == 40

    first_pass = await client.get(
        f"{BASE}/configurations/{configuration_id}/review", headers=owner
    )
    assert first_pass.json()["accessible_seats"] == 1

    # Generating twice without asking is refused: it would destroy 40 seats.
    again = await client.post(
        f"{BASE}/sections/{section_id}/seats",
        headers=owner,
        json={"row_count": 2, "seats_per_row": 5, "replace": False},
    )
    assert again.status_code == 409

    # Regenerating replaces *everything*, exceptions included: this run names
    # no wheelchair spaces, so the sector no longer has one. That is the
    # behaviour the red confirmation button in the admin screen warns about,
    # and it is asserted here so it cannot change quietly.
    replaced = await client.post(
        f"{BASE}/sections/{section_id}/seats",
        headers=owner,
        json={"row_count": 5, "seats_per_row": 10, "replace": True},
    )
    assert replaced.status_code == 200
    assert replaced.json()["seats"] == 50

    # Step 5 — a gate, and the sectors it admits to.
    gate = await client.post(
        f"{BASE}/configurations/{configuration_id}/gates",
        headers=owner,
        json={
            "name": "Poarta A",
            "code": "A",
            "kind": "PUBLIC",
            "supporter_side": "ANY",
            "is_accessible": True,
            "section_ids": [section_id],
        },
    )
    assert gate.status_code == 201, gate.text

    # Step 7 — review, then publish.
    review = await client.get(f"{BASE}/configurations/{configuration_id}/review", headers=owner)
    assert review.status_code == 200, review.text
    summary = review.json()
    assert summary["total_capacity"] == 50
    assert summary["reserved_seats"] == 50
    assert summary["accessible_seats"] == 0, "the regeneration should have replaced them"
    assert summary["publishable"] is True

    published = await client.post(
        f"{BASE}/configurations/{configuration_id}/publish", headers=owner
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "PUBLISHED"
    assert published.json()["total_capacity"] == 50

    # And the freeze is real, over HTTP: the editor's own calls are refused.
    frozen = await client.post(
        f"{BASE}/configurations/{configuration_id}/stands",
        headers=owner,
        json={"name": "Too late", "code": "TL", "geometry": _box(0, 0, 10, 10)},
    )
    assert frozen.status_code == 409
    assert frozen.json()["code"] == "CONFLICT"

    # Editing means a new version, which is editable again.
    forked = await client.post(f"{BASE}/configurations/{configuration_id}/fork", headers=owner)
    assert forked.status_code == 201, forked.text
    draft = forked.json()
    assert draft["status"] == "DRAFT"
    assert draft["version"] == 2
    assert draft["forked_from_id"] == configuration_id

    # The copy carries the seats — and they are *new* rows, so the published
    # version keeps pointing at seats no later edit can reach.
    copied = await client.get(f"{BASE}/configurations/{draft['id']}/review", headers=owner)
    assert copied.status_code == 200
    assert copied.json()["total_capacity"] == 50

    layout = await client.get(f"{BASE}/configurations/{draft['id']}/layout", headers=owner)
    assert layout.status_code == 200
    original = await client.get(
        f"{BASE}/configurations/{configuration_id}/layout", headers=owner
    )
    new_seat_ids = {
        seat["id"]
        for s in layout.json()["stands"]
        for sec in s["sections"]
        for row in sec["rows"]
        for seat in row["seats"]
    }
    old_seat_ids = {
        seat["id"]
        for s in original.json()["stands"]
        for sec in s["sections"]
        for row in sec["rows"]
        for seat in row["seats"]
    }
    assert new_seat_ids and not (new_seat_ids & old_seat_ids), (
        "a forked configuration shares seat rows with the published one it came from"
    )


async def test_a_sector_without_seats_is_a_warning_not_a_refusal(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    """A club halfway through drawing its ground must not be blocked by itself.

    Missing seats and a missing gate are warnings. Only a layout that sells
    nothing at all stops publication.
    """
    owner = as_user("owner")
    suffix = uuid4().hex[:6].upper()

    venue = await client.post(
        f"{BASE}/venues",
        headers=owner,
        json={
            "club_id": demo["club_id"],
            "name": f"Half Built {suffix}",
            "code": f"HB{suffix}",
        },
    )
    venue_id = venue.json()["id"]
    config = await client.post(
        f"{BASE}/venues/{venue_id}/configurations",
        headers=owner,
        json={"name": f"Draft {suffix}"},
    )
    configuration_id = config.json()["id"]

    stand = await client.post(
        f"{BASE}/configurations/{configuration_id}/stands",
        headers=owner,
        json={"name": "Peluză", "code": "PN", "geometry": _box(300, 90, 400, 150)},
    )
    await client.post(
        f"{BASE}/stands/{stand.json()['id']}/sections",
        headers=owner,
        json={
            "name": "Peluză Nord",
            "code": "PN1",
            "kind": "GENERAL_ADMISSION",
            "declared_capacity": 300,
            "geometry": _box(310, 100, 380, 130),
        },
    )

    review = await client.get(f"{BASE}/configurations/{configuration_id}/review", headers=owner)
    summary = review.json()
    codes = {finding["code"] for finding in summary["findings"]}

    assert "SECTION_WITHOUT_GATE" in codes
    assert "SECTION_WITHOUT_PRICE_ZONE" in codes
    assert all(finding["severity"] == "WARNING" for finding in summary["findings"])
    assert summary["publishable"] is True, "warnings must not block a club mid-setup"


async def test_an_empty_configuration_cannot_be_published(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    owner = as_user("owner")
    suffix = uuid4().hex[:6].upper()

    venue = await client.post(
        f"{BASE}/venues",
        headers=owner,
        json={"club_id": demo["club_id"], "name": f"Empty {suffix}", "code": f"EM{suffix}"},
    )
    config = await client.post(
        f"{BASE}/venues/{venue.json()['id']}/configurations",
        headers=owner,
        json={"name": f"Nothing {suffix}"},
    )

    published = await client.post(
        f"{BASE}/configurations/{config.json()['id']}/publish", headers=owner
    )
    assert published.status_code == 422
    assert published.json()["code"] == "VALIDATION_ERROR"
