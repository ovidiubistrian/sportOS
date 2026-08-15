"""The outbox actually delivers, and does so exactly once per handler."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from app.events.base import EVENT_TYPES, DomainEvent, PlayerRegistered
from app.events.publisher import claim

pytestmark = pytest.mark.events


class TestEventContract:
    def test_every_event_declares_its_identity(self) -> None:
        for event_type, event_class in EVENT_TYPES.items():
            assert event_type, f"{event_class.__name__} has an empty event_type"
            assert event_class.aggregate_type, f"{event_type} has no aggregate_type"

    def test_event_types_are_unique(self) -> None:
        subclasses = [c for c in DomainEvent.__subclasses__() if c.event_type]
        assert len(subclasses) == len(EVENT_TYPES), "two events share an event_type"

    def test_an_event_without_identity_cannot_be_constructed(self) -> None:
        with pytest.raises(TypeError, match="event_type"):
            DomainEvent(aggregate_id=new_id())

    def test_payloads_carry_no_pii(self) -> None:
        """A payload key that looks like PII is a review failure, not a runtime one.

        Events are persisted, retried and logged; keeping them PII-free is what
        stops erasure from having to rewrite event history.
        """
        forbidden = {"email", "phone", "first_name", "last_name", "display_name", "address"}
        event = PlayerRegistered.of(new_id(), tenant_id=new_id(), club_id="x", team_id=None)
        assert not (set(event.payload) & forbidden)


class TestPublishing:
    async def test_publish_is_atomic_with_the_change(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        admin_engine: AsyncEngine,
    ) -> None:
        """A rejected create must leave no event behind."""
        async with admin_engine.connect() as conn:
            before = int(await conn.scalar(text("SELECT count(*) FROM outbox_event")) or 0)

        # Fails validation, so the transaction rolls back.
        response = await client.post(
            "/api/v1/players",
            headers=as_user("owner"),
            json={"club_id": demo["club_id"], "first_name": "", "last_name": "X"},
        )
        assert response.status_code == 422

        async with admin_engine.connect() as conn:
            after = int(await conn.scalar(text("SELECT count(*) FROM outbox_event")) or 0)
        assert after == before, "an event survived a rolled-back transaction"

    async def test_creating_a_player_emits_an_event(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        admin_engine: AsyncEngine,
    ) -> None:
        response = await client.post(
            "/api/v1/players",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "first_name": "Outbox",
                "last_name": "Probe",
            },
        )
        assert response.status_code == 201
        player_id = response.json()["id"]

        async with admin_engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT event_type, tenant_id, payload FROM outbox_event "
                        "WHERE aggregate_id = :id"
                    ),
                    {"id": player_id},
                )
            ).first()

        assert row is not None, "no event was written for the created player"
        assert row[0] == "players.player_registered"
        assert str(row[1]) == demo["tenant_id"]


class TestIdempotency:
    async def test_a_handler_claims_an_event_only_once(self, admin_engine: AsyncEngine) -> None:
        from app.core.db import SessionFactory

        event_id = new_id()
        handler = f"test.handler.{event_id}"

        async with SessionFactory() as session:
            await session.begin()
            first = await claim(session, handler, event_id)
            await session.commit()

        async with SessionFactory() as session:
            await session.begin()
            second = await claim(session, handler, event_id)
            await session.commit()

        assert first is True, "the first delivery should be claimed"
        assert second is False, "a duplicate delivery must be a no-op"

    async def test_concurrent_claims_produce_exactly_one_winner(
        self, admin_engine: AsyncEngine
    ) -> None:
        """At-least-once delivery plus concurrent relays must still run work once."""
        from app.core.db import SessionFactory

        event_id = new_id()
        handler = f"test.concurrent.{event_id}"

        async def attempt() -> bool:
            async with SessionFactory() as session:
                await session.begin()
                try:
                    result = await claim(session, handler, event_id)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    return False
                return result

        results = await asyncio.gather(*(attempt() for _ in range(10)))
        assert sum(1 for r in results if r) == 1, (
            f"expected exactly one claim to win, got {sum(1 for r in results if r)}"
        )


class TestRelay:
    async def test_relay_delivers_and_marks_published(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        admin_engine: AsyncEngine,
    ) -> None:
        """End to end through the *running* relay container, not an in-process call.

        This is what makes the test meaningful: it proves the deployed process
        picks the event up, not just that `dispatch_once` works when called by
        hand.
        """
        response = await client.post(
            "/api/v1/players",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "first_name": "Relay",
                "last_name": "Probe",
            },
        )
        assert response.status_code == 201
        player_id = response.json()["id"]

        status = None
        for _ in range(30):
            async with admin_engine.connect() as conn:
                status = await conn.scalar(
                    text("SELECT status FROM outbox_event WHERE aggregate_id = :id"),
                    {"id": player_id},
                )
            if status == "PUBLISHED":
                break
            await asyncio.sleep(0.3)

        assert status == "PUBLISHED", (
            f"the relay did not deliver within ~9s (status={status}). "
            "Is the outbox-relay service running?"
        )

    async def test_the_handler_recorded_its_claim(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        admin_engine: AsyncEngine,
    ) -> None:
        """Delivery is only proven if a consumer actually claimed the event."""
        async with admin_engine.connect() as conn:
            claims = int(
                await conn.scalar(
                    text(
                        "SELECT count(*) FROM processed_event "
                        "WHERE handler_name = 'events.record_player_registration'"
                    )
                )
                or 0
            )
        assert claims > 0, "no handler ever claimed a player registration event"

    async def test_unpublished_events_do_not_accumulate_as_failed(
        self, admin_engine: AsyncEngine
    ) -> None:
        async with admin_engine.connect() as conn:
            dead = int(
                await conn.scalar(
                    text("SELECT count(*) FROM outbox_event WHERE status IN ('DEAD','FAILED')")
                )
                or 0
            )
        assert dead == 0, f"{dead} events failed delivery"


def test_publish_is_the_only_way_to_emit() -> None:
    """`OutboxEvent` must not be constructed directly outside the publisher."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    offenders = [
        path.relative_to(root)
        for path in root.rglob("*.py")
        if "OutboxEvent(" in path.read_text()
        and path.name not in {"publisher.py", "models.py", "relay.py"}
    ]
    assert not offenders, (
        f"These modules build outbox rows directly instead of calling publish(): {offenders}"
    )
