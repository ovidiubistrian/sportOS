from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Row, Select, and_, func, or_, select

from app.authz.service import ScopeFilter
from app.core.pagination import PageRequest, count_for
from app.core.repository import TenantScopedRepository
from app.identity.models import Person
from app.players.models import Player, PlayerRegistration
from app.players.schemas import PlayerFilters
from app.teams.models import Team


class PlayerRepository(TenantScopedRepository[Player]):
    model = Player

    def _listing_query(self) -> Select[Any]:
        """Player joined to identity and current registration.

        The registration join is restricted to live rows so a player who moved
        from U15 to U17 appears once, in U17 — not twice.
        """
        live_registration = and_(
            PlayerRegistration.player_id == Player.id,
            PlayerRegistration.tenant_id == Player.tenant_id,
            PlayerRegistration.ended_on.is_(None),
        )
        return (
            select(
                Player,
                Person,
                Team,
                PlayerRegistration.shirt_number,
            )
            .join(
                Person,
                and_(Person.id == Player.person_id, Person.tenant_id == Player.tenant_id),
            )
            .outerjoin(PlayerRegistration, live_registration)
            .outerjoin(
                Team,
                and_(Team.id == PlayerRegistration.team_id, Team.tenant_id == Player.tenant_id),
            )
            .where(Player.tenant_id == self.tenant_id)
        )

    @staticmethod
    def _apply_filters(stmt: Select[Any], filters: PlayerFilters) -> Select[Any]:
        if filters.club_id:
            stmt = stmt.where(Player.club_id == filters.club_id)
        if filters.team_id:
            stmt = stmt.where(PlayerRegistration.team_id == filters.team_id)
        if filters.season_id:
            stmt = stmt.where(PlayerRegistration.season_id == filters.season_id)
        if filters.status:
            stmt = stmt.where(Player.status == filters.status)
        if filters.q:
            # Prefix match on either name part; backed by ix_person_name.
            pattern = f"{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    Person.last_name.ilike(pattern),
                    Person.first_name.ilike(pattern),
                    Person.display_name.ilike(f"%{filters.q.strip()}%"),
                )
            )
        return stmt

    @staticmethod
    def _apply_scope(stmt: Select[Any], scope: ScopeFilter) -> Select[Any]:
        """Restrict to the rows this caller may see.

        A team-scoped coach listing "all players" gets their own teams, not the
        club. Without this the permission check would pass and the query would
        over-return — the exact bug the scope model exists to prevent.
        """
        if scope.unrestricted:
            return stmt
        if scope.is_empty:
            return stmt.where(False)
        conditions = []
        if scope.club_ids:
            conditions.append(Player.club_id.in_(scope.club_ids))
        if scope.team_ids:
            conditions.append(PlayerRegistration.team_id.in_(scope.team_ids))
        return stmt.where(or_(*conditions))

    async def list_page(
        self, filters: PlayerFilters, scope: ScopeFilter, page: PageRequest
    ) -> tuple[list[Row[Any]], int | None, bool]:
        stmt = self._apply_scope(self._apply_filters(self._listing_query(), filters), scope)

        total: int | None = None
        is_estimate = False
        if page.with_total:
            total, is_estimate = await count_for(self.session, stmt)

        stmt = (
            stmt.order_by(Person.last_name, Person.first_name, Player.id)
            .limit(page.limit)
            .offset(page.offset)
        )
        rows = (await self.session.execute(stmt)).all()
        return list(rows), total, is_estimate

    async def get_detail(self, player_id: UUID, scope: ScopeFilter) -> Row[Any] | None:
        stmt = self._apply_scope(self._listing_query().where(Player.id == player_id), scope)
        return (await self.session.execute(stmt)).first()

    async def count_for_club(self, club_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Player)
            .where(
                Player.tenant_id == self.tenant_id,
                Player.club_id == club_id,
                Player.status != "DEPARTED",
            )
        )
        return int(await self.session.scalar(stmt) or 0)

    async def shirt_number_taken(
        self,
        team_id: UUID,
        season_id: UUID,
        shirt_number: int,
        *,
        exclude_player: UUID | None = None,
    ) -> bool:
        """`exclude_player` is for a player keeping their own number on a move —
        otherwise the check finds their existing registration and refuses."""
        stmt = select(PlayerRegistration.id).where(
            PlayerRegistration.tenant_id == self.tenant_id,
            PlayerRegistration.team_id == team_id,
            PlayerRegistration.season_id == season_id,
            PlayerRegistration.shirt_number == shirt_number,
            PlayerRegistration.ended_on.is_(None),
        )
        if exclude_player is not None:
            stmt = stmt.where(PlayerRegistration.player_id != exclude_player)
        return (await self.session.scalar(stmt)) is not None
