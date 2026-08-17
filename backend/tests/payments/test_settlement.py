"""What an order does when the gateway answers, and when it does not.

The gateway is a stand-in. What is under test is not BT iPay — it is the two
decisions that lose money when they are wrong: confirming an order more than
once, and giving up on one that is still being paid for.

A real gateway is not reachable from the suite and would not help if it were.
The states that matter are the ones that are hard to produce on demand — a
buyer halfway through authenticating, a bank that stops answering — and a
stand-in produces them exactly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Every model, so the mappers can resolve the foreign keys `shop_order` carries
# into tables no other import in this file would have loaded.
from app.core import model_registry  # noqa: F401
from app.core.config import settings
from app.core.db import bind_tenant
from app.ordering import payments
from app.ordering.models import Order
from app.ordering.service import new_reference
from app.payments.base import PaymentProviderError, SessionStatus
from app.payments.models import PaymentAttempt

pytestmark = pytest.mark.commerce


class FakeGateway:
    """Answers with whatever the test wants, or refuses to answer at all."""

    key = "btipay"
    display_name = "Fake"

    def __init__(
        self, *, status: SessionStatus | None = None, unreachable: bool = False
    ) -> None:
        self._status = status
        self._unreachable = unreachable
        self.asked: list[str] = []

    async def get_session_status(self, session_id: str) -> SessionStatus:
        self.asked.append(session_id)
        if self._unreachable:
            raise PaymentProviderError("the gateway is not answering")
        assert self._status is not None
        return self._status


def answering(code: int, state: str, paid: int = 0) -> FakeGateway:
    """A gateway reporting one of BT's own order states.

    Both the number and the word, because they disagree on purpose: 0 and 5
    share a word and demand opposite decisions.
    """
    return FakeGateway(
        status=SessionStatus(
            status=state, paid_amount_minor=paid, currency="RON", raw={"orderStatus": code}
        )
    )


@pytest.fixture
def use_gateway(monkeypatch: pytest.MonkeyPatch):
    """Put a stand-in behind the provider the code under test would build."""

    def _use(gateway: Any) -> Any:
        async def _build(*_args: Any, **_kwargs: Any) -> Any:
            return gateway

        monkeypatch.setattr(payments, "build_provider", _build)
        return gateway

    return _use


@pytest.fixture
async def db(demo: dict[str, Any]) -> AsyncIterator[AsyncSession]:
    """A session bound to the demo tenant, thrown away at the end.

    Its own engine with no pooling, for the reason `admin_engine` gives: the
    module-level one pools against the loop that imported it, and pytest hands
    each test a fresh one. Rolled back rather than tidied up, so a test that
    fails halfway still leaves the database as it found it.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool, echo=False)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    try:
        async with factory() as session:
            await session.begin()
            await bind_tenant(session, UUID(demo["tenant_id"]))
            try:
                yield session
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def order_awaiting_card(
    demo: dict[str, Any], db: AsyncSession
) -> tuple[UUID, Order, str]:
    """An order waiting on a card, with one attempt registered against it."""
    tenant_id = UUID(demo["tenant_id"])
    session_id = uuid4().hex
    order = Order(
        tenant_id=tenant_id,
        club_id=UUID(demo["club_id"]),
        reference=new_reference(),
        status="AWAITING_PAYMENT",
        currency="RON",
        subtotal_minor=2500,
        total_minor=2500,
        buyer_name="Test Supporter",
        payment_method="CARD",
    )
    db.add(order)
    await db.flush()
    db.add(
        PaymentAttempt(
            tenant_id=tenant_id,
            order_id=order.id,
            provider="btipay",
            session_id=session_id,
            amount_minor=2500,
            currency="RON",
            state="pending",
        )
    )
    await db.flush()
    return tenant_id, order, session_id


async def attempt_for(db: AsyncSession, session_id: str) -> PaymentAttempt:
    return await db.scalar(
        select(PaymentAttempt).where(PaymentAttempt.session_id == session_id)
    )


class TestSettling:
    async def test_a_paid_order_becomes_collectable_exactly_once(
        self, db: AsyncSession, order_awaiting_card: tuple[UUID, Order, str]
    ) -> None:
        """The second call is a supporter refreshing the page they landed on.

        It has to reach the same conclusion and report that it changed nothing,
        because what hangs off "this call confirmed it" is the receipt — and a
        club sending two receipts for one shirt is a support ticket.
        """
        tenant_id, _order, session_id = order_awaiting_card
        paid = SessionStatus(
            status="completed", paid_amount_minor=2500, raw={"orderStatus": 2}
        )

        settled, just_paid = await payments.settle(db, tenant_id, session_id, paid)
        assert just_paid is True
        assert settled.status == "AWAITING_COLLECTION"

        settled, just_paid = await payments.settle(db, tenant_id, session_id, paid)
        assert just_paid is False, "a refresh must not confirm a second time"
        assert settled.status == "AWAITING_COLLECTION"

    async def test_a_held_authorisation_is_collectable_too(
        self, db: AsyncSession, order_awaiting_card: tuple[UUID, Order, str]
    ) -> None:
        """Two-phase: the money is committed as far as the buyer is concerned,
        and the club captures it later. The shirt is theirs either way."""
        tenant_id, _order, session_id = order_awaiting_card
        held = SessionStatus(
            status="approved", paid_amount_minor=2500, raw={"orderStatus": 1}
        )

        settled, just_paid = await payments.settle(db, tenant_id, session_id, held)
        assert just_paid is True
        assert settled.status == "AWAITING_COLLECTION"

    async def test_a_refusal_leaves_the_order_unpaid_and_stops_asking(
        self, db: AsyncSession, order_awaiting_card: tuple[UUID, Order, str]
    ) -> None:
        tenant_id, _order, session_id = order_awaiting_card

        settled, just_paid = await payments.settle(
            db, tenant_id, session_id, SessionStatus(status="failed", raw={"orderStatus": 6})
        )
        assert just_paid is False
        assert settled.status == "AWAITING_PAYMENT"
        assert (await attempt_for(db, session_id)).settled_at is not None

    async def test_a_session_nobody_registered_changes_nothing(
        self, db: AsyncSession, demo: dict[str, Any]
    ) -> None:
        """A return URL can be replayed, guessed, or arrive for another tenant."""
        settled, just_paid = await payments.settle(
            db,
            UUID(demo["tenant_id"]),
            "not-a-session-we-minted",
            SessionStatus(status="completed"),
        )
        assert settled is None
        assert just_paid is False


class TestReconciling:
    """For the buyer whose browser never came back."""

    async def test_a_completed_payment_is_found_and_confirmed(
        self, db: AsyncSession, order_awaiting_card: tuple[UUID, Order, str], use_gateway
    ) -> None:
        _tenant_id, order, _session_id = order_awaiting_card
        use_gateway(answering(2, "completed", 2500))

        assert await payments.reconcile_order(db, order) == "paid"
        assert order.status == "AWAITING_COLLECTION"

    @pytest.mark.parametrize(
        ("code", "state", "why"),
        [
            (5, "pending", "the buyer is on their bank's authentication screen"),
            (1, "approved", "the money is already held"),
        ],
    )
    async def test_a_payment_in_flight_is_never_given_up_on(
        self,
        db: AsyncSession,
        order_awaiting_card: tuple[UUID, Order, str],
        use_gateway,
        code: int,
        state: str,
        why: str,
    ) -> None:
        """The expensive one.

        Order status 5 arrives as the same word as "nobody has tried to pay",
        so a reconciliation reading only the word would give up on an order
        somebody is in the middle of paying for — and the payment would then
        land against an order that had been cancelled and its stock returned.
        """
        _tenant_id, order, session_id = order_awaiting_card
        use_gateway(answering(code, state))

        assert await payments.reconcile_order(db, order) == "in_progress", why
        assert (await attempt_for(db, session_id)).settled_at is None

    @pytest.mark.parametrize(
        ("code", "state"), [(0, "pending"), (6, "failed")]
    )
    async def test_a_dead_attempt_may_be_given_up_on(
        self,
        db: AsyncSession,
        order_awaiting_card: tuple[UUID, Order, str],
        use_gateway,
        code: int,
        state: str,
    ) -> None:
        """0 is registered and abandoned, 6 is refused. Neither will ever pay."""
        _tenant_id, order, _session_id = order_awaiting_card
        use_gateway(answering(code, state))

        assert await payments.reconcile_order(db, order) == "unpaid"

    async def test_an_unreachable_gateway_decides_nothing(
        self, db: AsyncSession, order_awaiting_card: tuple[UUID, Order, str], use_gateway
    ) -> None:
        """Silence is not a refusal. Giving up on a failed status call would
        throw away real orders every time the bank had a bad minute."""
        _tenant_id, order, session_id = order_awaiting_card
        use_gateway(FakeGateway(unreachable=True))

        assert await payments.reconcile_order(db, order) == "unreachable"
        assert order.status == "AWAITING_PAYMENT"
        assert (await attempt_for(db, session_id)).settled_at is None

    async def test_every_attempt_is_asked_about_not_only_the_last(
        self,
        db: AsyncSession,
        demo: dict[str, Any],
        order_awaiting_card: tuple[UUID, Order, str],
        use_gateway,
    ) -> None:
        """A buyer who presses pay twice and completes the *first* attempt.

        Nothing on the order is overwritten by the second attempt, because the
        order carries no single payment reference — so the completed one is
        still there to be found. This is the failure that silently loses a
        payment in a design that keeps one reference per purchase.
        """
        tenant_id, order, first_session = order_awaiting_card
        second_session = uuid4().hex
        db.add(
            PaymentAttempt(
                tenant_id=tenant_id,
                order_id=order.id,
                provider="btipay",
                session_id=second_session,
                amount_minor=2500,
                currency="RON",
                state="pending",
            )
        )
        await db.flush()

        gateway = FakeGateway()

        async def answer(session_id: str) -> SessionStatus:
            gateway.asked.append(session_id)
            if session_id == first_session:
                return SessionStatus(
                    status="completed", paid_amount_minor=2500, raw={"orderStatus": 2}
                )
            return SessionStatus(status="pending", raw={"orderStatus": 0})

        gateway.get_session_status = answer  # type: ignore[method-assign]
        use_gateway(gateway)

        assert await payments.reconcile_order(db, order) == "paid"
        assert order.status == "AWAITING_COLLECTION"
        assert first_session in gateway.asked
