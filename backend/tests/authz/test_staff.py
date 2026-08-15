"""Staff logins, and the one rule that must never bend.

A club administrator can hand out access. What they must not be able to do is
hand out *more* access than they hold — because that turns any account worth
phishing into every account worth phishing. Most of this file is that rule,
approached from several directions.

Split deliberately in two. Granting a role is a *sensitive* permission, so
every mutating route demands a second factor, and the test users sign in with a
password — which means the rules themselves cannot be exercised over HTTP. So
the routes are tested for the refusal they must give, and the rules are tested
in-process against the same real database, where they can be pushed properly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.authz import staff_service as staff
from app.authz.models import Role, RoleAssignment
from app.authz.permissions import EffectivePermissions
from app.authz.role_templates import BY_KEY_TEMPLATE
from app.authz.scope import Scope
from app.core.context import Principal, RequestContext
from app.core.errors import Conflict, ValidationFailed

# Every model, so the foreign keys between modules resolve when the mappers are
# configured in-process. The application does this at start-up.
from app.core.model_registry import *  # noqa: F403
from app.identity.models import UserAccount

pytestmark = pytest.mark.staff

BASE = "/api/v1"


def unique_email(prefix: str) -> str:
    # A domain nobody can receive at: these logins are never signed into.
    return f"{prefix}-{uuid4().hex[:10]}@staffprobe.example.com"


async def _forget(admin_engine: Any, email: str) -> None:
    """Undo an invitation in both systems."""
    from app.identity.keycloak import get_admin

    async with admin_engine.begin() as conn:
        subject = (
            await conn.execute(
                text("SELECT subject_id FROM user_account WHERE email = :e"), {"e": email}
            )
        ).first()
        for statement in (
            "DELETE FROM role_assignment WHERE user_id IN "
            "(SELECT id FROM user_account WHERE email = :e)",
            "DELETE FROM person WHERE user_id IN "
            "(SELECT id FROM user_account WHERE email = :e)",
            "DELETE FROM user_account WHERE email = :e",
        ):
            await conn.execute(text(statement), {"e": email})

    if subject:
        await get_admin().delete_user(subject[0])


def context(
    tenant_id: UUID,
    role_key: str,
    *,
    club_id: UUID | None = None,
    user_id: UUID | None = None,
) -> RequestContext:
    """A caller holding exactly one role's permissions, at one scope.

    Built from the same templates the product ships, so a test cannot pass by
    describing a role that does not exist.
    """
    template = BY_KEY_TEMPLATE[role_key]
    scope = (
        Scope.club(tenant_id, club_id)
        if club_id is not None and template.scope_level.name == "CLUB"
        else Scope.tenant(tenant_id)
    )
    return RequestContext(
        request_id="test",
        tenant_id=tenant_id,
        principal=Principal(
            user_id=user_id or uuid4(),
            subject_id="test-subject",
            email="test@example.com",
            auth_time=datetime.now(UTC),
            amr=frozenset({"pwd", "otp"}),
        ),
        permissions=EffectivePermissions(
            grants={key: frozenset({scope}) for key in template.permissions}
        ),
    )


@pytest.fixture
async def session(admin_engine: Any) -> AsyncIterator[Any]:
    """A writable session on the platform role, rolled back at the end.

    Nothing these tests write survives them, which matters more than usual
    here: a stray role assignment is a person who can quietly do things.
    """
    maker = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with maker() as db:
        try:
            yield db
        finally:
            await db.rollback()


@pytest.fixture
async def stranger(session: Any) -> AsyncIterator[UserAccount]:
    """An account with no role anywhere, to be given one."""
    account = UserAccount(
        subject_id=f"test-{uuid4().hex}",
        email=f"stranger-{uuid4().hex[:8]}@staffprobe.example.com",
        email_verified=False,
    )
    session.add(account)
    await session.flush()
    yield account


class TestTheEscalationGuard:
    """Nobody hands out access they do not hold. This is the rule."""

    def test_an_academy_director_cannot_appoint_a_club_administrator(self) -> None:
        """CLUB_ADMIN carries commerce and role management; they hold neither.

        Without this, an academy director could promote themselves by proxy:
        invite an address they control, give it the bigger role, sign in.
        """
        tenant, club = uuid4(), uuid4()
        ctx = context(tenant, "ACADEMY_DIRECTOR", club_id=club)
        assert not staff.may_grant(ctx, "CLUB_ADMIN", Scope.club(tenant, club))

    def test_an_academy_director_can_appoint_a_coach(self) -> None:
        """The rule refuses more, not everything — the job still works."""
        tenant, club, team = uuid4(), uuid4(), uuid4()
        ctx = context(tenant, "ACADEMY_DIRECTOR", club_id=club)
        assert staff.may_grant(ctx, "COACH", Scope.team(tenant, club, team))

    def test_a_club_administrator_can_appoint_the_person_who_writes_the_news(
        self,
    ) -> None:
        tenant, club = uuid4(), uuid4()
        ctx = context(tenant, "CLUB_ADMIN", club_id=club)
        assert staff.may_grant(ctx, "CONTENT_MANAGER", Scope.club(tenant, club))

    def test_a_club_role_cannot_reach_another_club(self) -> None:
        """Holding it here is not holding it there."""
        tenant, ours, theirs = uuid4(), uuid4(), uuid4()
        ctx = context(tenant, "CLUB_ADMIN", club_id=ours)
        assert staff.may_grant(ctx, "CONTENT_MANAGER", Scope.club(tenant, ours))
        assert not staff.may_grant(ctx, "CONTENT_MANAGER", Scope.club(tenant, theirs))

    def test_a_club_administrator_cannot_invent_a_tenant_wide_role(self) -> None:
        """FINANCE_MANAGER is tenant-scoped: a club admin has no such reach."""
        tenant, club = uuid4(), uuid4()
        ctx = context(tenant, "CLUB_ADMIN", club_id=club)
        assert not staff.may_grant(ctx, "FINANCE_MANAGER", Scope.tenant(tenant))

    def test_nobody_hands_the_tenant_away_from_this_screen(self) -> None:
        """Succession is not staffing, and does not belong behind an invite form."""
        tenant = uuid4()
        ctx = context(tenant, "TENANT_OWNER")
        assert not staff.may_grant(ctx, "TENANT_OWNER", Scope.tenant(tenant))

    def test_a_tenant_cannot_mint_a_platform_role(self) -> None:
        tenant = uuid4()
        ctx = context(tenant, "TENANT_OWNER")
        for key in ("SUPER_ADMIN", "PLATFORM_SUPPORT"):
            assert not staff.may_grant(ctx, key, Scope.tenant(tenant))
        assert key not in staff.invitable_roles()

    def test_medical_access_needs_medical_access_to_give(self) -> None:
        """Clinical records are special-category data, and the rule covers them
        for free — a club admin holds no medical permission, so cannot appoint
        somebody who would."""
        tenant, club = uuid4(), uuid4()
        ctx = context(tenant, "CLUB_ADMIN", club_id=club)
        assert not staff.may_grant(ctx, "MEDICAL_STAFF", Scope.club(tenant, club))


class TestWhatAScopeMeans:
    def test_a_team_role_without_a_team_is_refused(self) -> None:
        """A coach with no team is not a narrower grant — it is a wider one."""
        with pytest.raises(ValidationFailed):
            staff.scope_for("COACH", uuid4(), uuid4(), None)

    def test_a_club_role_without_a_club_is_refused(self) -> None:
        with pytest.raises(ValidationFailed):
            staff.scope_for("CONTENT_MANAGER", uuid4(), None, None)

    def test_a_tenant_role_needs_neither(self) -> None:
        tenant = uuid4()
        assert staff.scope_for("FINANCE_MANAGER", tenant, None, None) == Scope.tenant(tenant)

    def test_an_unknown_role_is_refused(self) -> None:
        with pytest.raises(ValidationFailed):
            staff.scope_for("PRESIDENT_FOR_LIFE", uuid4(), None, None)


class TestGrantingAndRevoking:
    async def test_granting_twice_is_granting_once(
        self, session: Any, stranger: UserAccount, demo: dict[str, Any]
    ) -> None:
        """The unique-grant constraint is real; the service must not trip it."""
        tenant = UUID(demo["tenant_id"])
        club = UUID(demo["club_id"])
        ctx = context(tenant, "CLUB_ADMIN", club_id=club)

        first = await staff.grant(
            session,
            ctx,
            user_id=stranger.id,
            role_key="CONTENT_MANAGER",
            club_id=club,
            team_id=None,
        )
        second = await staff.grant(
            session,
            ctx,
            user_id=stranger.id,
            role_key="CONTENT_MANAGER",
            club_id=club,
            team_id=None,
        )
        assert first.id == second.id

    async def test_re_hiring_reinstates_rather_than_duplicates(
        self, session: Any, stranger: UserAccount, demo: dict[str, Any]
    ) -> None:
        """Somebody who comes back is the same relationship, not a second one."""
        tenant = UUID(demo["tenant_id"])
        club = UUID(demo["club_id"])
        ctx = context(tenant, "CLUB_ADMIN", club_id=club)

        first = await staff.grant(
            session,
            ctx,
            user_id=stranger.id,
            role_key="CONTENT_MANAGER",
            club_id=club,
            team_id=None,
        )
        await staff.revoke(session, ctx, user_id=stranger.id, reason="Left")
        assert first.revoked_at is not None

        again = await staff.grant(
            session,
            ctx,
            user_id=stranger.id,
            role_key="CONTENT_MANAGER",
            club_id=club,
            team_id=None,
        )
        assert again.id == first.id
        assert again.revoked_at is None

    async def test_a_grant_beyond_the_granter_is_refused_at_the_service(
        self, session: Any, stranger: UserAccount, demo: dict[str, Any]
    ) -> None:
        """The guard is in the service, not only in the route.

        Which matters: the route is one caller, and the next one will not
        remember to check.
        """
        tenant = UUID(demo["tenant_id"])
        club = UUID(demo["club_id"])
        ctx = context(tenant, "ACADEMY_DIRECTOR", club_id=club)

        with pytest.raises(ValidationFailed):
            await staff.grant(
                session,
                ctx,
                user_id=stranger.id,
                role_key="CLUB_ADMIN",
                club_id=club,
                team_id=None,
            )

    async def test_revoking_ends_every_grant_this_tenant_made(
        self, session: Any, stranger: UserAccount, demo: dict[str, Any]
    ) -> None:
        tenant = UUID(demo["tenant_id"])
        club = UUID(demo["club_id"])
        ctx = context(tenant, "CLUB_ADMIN", club_id=club)

        await staff.grant(
            session,
            ctx,
            user_id=stranger.id,
            role_key="CONTENT_MANAGER",
            club_id=club,
            team_id=None,
        )
        await staff.grant(
            session,
            ctx,
            user_id=stranger.id,
            role_key="TEAM_MANAGER",
            club_id=club,
            team_id=UUID(demo["u15_team_id"]),
        )

        assert await staff.revoke(session, ctx, user_id=stranger.id) == 2
        live = await session.scalars(
            select(RoleAssignment).where(
                RoleAssignment.user_id == stranger.id,
                RoleAssignment.revoked_at.is_(None),
            )
        )
        assert list(live) == []

    async def test_you_cannot_remove_your_own_access(
        self, session: Any, demo: dict[str, Any]
    ) -> None:
        """An owner who revokes their own last role locks the club."""
        tenant = UUID(demo["tenant_id"])
        me = uuid4()
        ctx = context(tenant, "CLUB_ADMIN", club_id=UUID(demo["club_id"]), user_id=me)
        with pytest.raises(ValidationFailed):
            await staff.revoke(session, ctx, user_id=me)

    async def test_the_last_owner_cannot_be_removed(
        self, session: Any, demo: dict[str, Any]
    ) -> None:
        """A tenant with no owner is a support ticket, not a state."""
        tenant = UUID(demo["tenant_id"])
        ctx = context(tenant, "TENANT_OWNER")

        owner_role = await session.scalar(select(Role).where(Role.key == "TENANT_OWNER"))
        owners = list(
            await session.scalars(
                select(RoleAssignment).where(
                    RoleAssignment.tenant_id == tenant,
                    RoleAssignment.role_id == owner_role.id,
                    RoleAssignment.revoked_at.is_(None),
                )
            )
        )
        assert owners, "the demo tenant should have an owner"

        # Leave exactly one, then try to remove them.
        for extra in owners[1:]:
            extra.revoked_at = datetime.now(UTC)
        await session.flush()

        with pytest.raises(Conflict):
            await staff.revoke(session, ctx, user_id=owners[0].user_id)

    async def test_a_lapsed_grant_does_not_count_as_working_here(
        self, session: Any, stranger: UserAccount, demo: dict[str, Any]
    ) -> None:
        """`valid_until` is honoured, so a season-long grant really ends."""
        tenant = UUID(demo["tenant_id"])
        club = UUID(demo["club_id"])
        ctx = context(tenant, "CLUB_ADMIN", club_id=club)

        grant = await staff.grant(
            session,
            ctx,
            user_id=stranger.id,
            role_key="CONTENT_MANAGER",
            club_id=club,
            team_id=None,
        )
        grant.valid_until = datetime.now(UTC) - timedelta(days=1)
        await session.flush()

        live = await staff.assignments_in(session, tenant)
        assert stranger.id not in {a.user_id for a in live}


class TestTheRoutes:
    """What the API does, given a caller who signed in with a password."""

    async def test_a_club_can_read_who_works_here(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get(f"{BASE}/staff", headers=as_user("owner"))
        assert response.status_code == 200
        assert any(row["role_key"] == "TENANT_OWNER" for row in response.json())

    async def test_the_role_list_marks_what_the_caller_cannot_grant(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """The screen can explain the refusal instead of hiding the option."""
        academy = (
            await client.get(
                f"{BASE}/staff/roles",
                headers=as_user("academy"),
                params={"club_id": demo["club_id"]},
            )
        ).json()
        by_key = {row["key"]: row for row in academy}

        assert by_key["CLUB_ADMIN"]["grantable"] is False
        # Never offered to anybody, at any scope.
        assert "TENANT_OWNER" not in by_key

        owner = (
            await client.get(
                f"{BASE}/staff/roles",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
            )
        ).json()
        assert {row["key"] for row in owner if row["grantable"]} >= {
            "CLUB_ADMIN",
            "CONTENT_MANAGER",
        }

    async def test_staffing_a_club_is_ordinary_work(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        admin_engine: Any,
    ) -> None:
        """A club secretary adding the news editor needs no second factor.

        Requiring one made the feature unusable: an owner can already delete
        every player without stepping up, so a lock on this alone bought no
        safety and cost the club its own staffing screen.
        """
        email = unique_email("ordinary")
        try:
            response = await client.post(
                f"{BASE}/staff",
                headers=as_user("owner"),
                json={
                    "email": email,
                    "first_name": "Ana",
                    "last_name": "Editor",
                    "role": "CONTENT_MANAGER",
                    "club_id": demo["club_id"],
                },
            )
            assert response.status_code == 201, response.text
            assert response.json()["role_key"] == "CONTENT_MANAGER"
        finally:
            await _forget(admin_engine, email)

    async def test_making_somebody_an_administrator_still_does(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """Delegation is the step that matters, and it is the one held back.

        CLUB_ADMIN carries `authz.role.manage`, so granting it hands over the
        power to hand out roles — the classic escalation step. Nothing is
        created on the way to this refusal.
        """
        response = await client.post(
            f"{BASE}/staff",
            headers=as_user("owner"),
            json={
                "email": unique_email("delegate"),
                "first_name": "Nou",
                "last_name": "Administrator",
                "role": "CLUB_ADMIN",
                "club_id": demo["club_id"],
            },
        )
        assert response.status_code == 401
        assert response.json()["code"] == "STEP_UP_REQUIRED"

    async def test_a_coach_cannot_even_read_the_staff_list(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Who else works here, and at what level, is not a coach's business."""
        response = await client.get(f"{BASE}/staff", headers=as_user("coach"))
        assert response.status_code == 403


class TestTheInvitationItself:
    """Against real Keycloak, because that is the half that can surprise us."""

    async def test_an_invitation_creates_a_login_with_no_password(
        self, admin_engine: Any
    ) -> None:
        from app.identity.keycloak import get_admin

        email = f"invite-{uuid4().hex[:10]}@staffprobe.example.com"
        admin = get_admin()
        created = await admin.invite_user(email=email, first_name="Ana", last_name="Editor")
        try:
            assert created.subject_id
            # Inviting the same address again is the same person, not a second
            # account — a coach at two clubs has one login.
            again = await admin.invite_user(email=email, first_name="Ana", last_name="Editor")
            assert again.subject_id == created.subject_id
            assert await admin.find_by_email(email) == created.subject_id
        finally:
            await admin.delete_user(created.subject_id)

        assert await admin.find_by_email(email) is None

    async def test_an_unknown_address_is_simply_unknown(self) -> None:
        from app.identity.keycloak import get_admin

        assert await get_admin().find_by_email("nobody@staffprobe.example.com") is None


async def test_no_test_left_a_stray_login_behind(admin_engine: Any) -> None:
    """The sweep. These tests write real rows in two systems."""
    async with admin_engine.connect() as conn:
        strays = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM user_account "
                    "WHERE email LIKE '%@staffprobe.example.com'"
                )
            )
        ).scalar_one()
    assert strays == 0
