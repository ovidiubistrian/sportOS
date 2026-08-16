from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Row, and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditService
from app.authz.service import ScopeFilter
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import Page, PageMeta, PageRequest
from app.events.base import PlayerRegistered, PlayerStatusChanged
from app.events.publisher import publish
from app.identity.models import Person, PersonRoleFlag
from app.players.models import Player, PlayerRegistration
from app.players.repository import PlayerRepository
from app.players.schemas import (
    PlayerCreate,
    PlayerDetail,
    PlayerFilters,
    PlayerSummary,
    PlayerUpdate,
    RegistrationChange,
    TeamSummary,
)
from app.teams.models import Season, Team

log = structlog.get_logger(__name__)


class PlayerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PlayerRepository(session)

    # --- queries -----------------------------------------------------------

    async def list_players(
        self, filters: PlayerFilters, scope: ScopeFilter, page: PageRequest
    ) -> Page[PlayerSummary]:
        rows, total, is_estimate = await self.repo.list_page(filters, scope, page)
        items = [_to_summary(row) for row in rows]
        await self._attach_photos(items, [row[0] for row in rows])
        return Page[PlayerSummary](
            data=items,
            page=PageMeta(
                limit=page.limit,
                offset=page.offset,
                total=total,
                total_is_estimate=is_estimate,
                has_more=len(items) == page.limit,
            ),
        )

    async def get_player(self, player_id: UUID, scope: ScopeFilter) -> PlayerDetail:
        row = await self.repo.get_detail(player_id, scope)
        if row is None:
            # Out of scope and non-existent are indistinguishable on purpose.
            raise NotFound(object_type="player", object_id=str(player_id))
        detail = _to_detail(row)
        await self._attach_photos([detail], [row[0]])
        return detail

    async def _attach_photos(self, items: list[Any], players: list[Player]) -> None:
        """Resolve squad photographs for a page of players, in one query.

        Resolved at read time rather than stored, so an image the club deletes
        degrades to no photograph instead of to a broken one on the team page.
        """
        wanted = {p.photo_media_id for p in players if p.photo_media_id}
        if not wanted:
            return

        from app.media import storage
        from app.media.models import MediaAsset

        urls = {
            asset.id: storage.public_url(asset.storage_key)
            for asset in await self.session.scalars(
                select(MediaAsset).where(MediaAsset.id.in_(wanted))
            )
        }
        for item, player in zip(items, players, strict=True):
            if player.photo_media_id:
                item.photo_url = urls.get(player.photo_media_id)

    # --- commands ----------------------------------------------------------

    async def create_player(self, payload: PlayerCreate, ctx: RequestContext) -> PlayerDetail:
        club = await self._require_club(payload.club_id)

        if payload.team_id is not None:
            await self._require_team(payload.team_id, club_id=club)
            if payload.season_id is None:
                payload.season_id = await self._current_season(club)
                if payload.season_id is None:
                    raise ValidationFailed(
                        "This club has no current season, so a player cannot be "
                        "registered to a team yet.",
                        fields=[{"field": "season_id", "code": "NO_CURRENT_SEASON"}],
                    )
            if payload.shirt_number is not None and await self.repo.shirt_number_taken(
                payload.team_id, payload.season_id, payload.shirt_number
            ):
                raise Conflict(
                    f"Shirt number {payload.shirt_number} is already taken in this team.",
                    code_detail="SHIRT_NUMBER_TAKEN",
                    shirt_number=payload.shirt_number,
                )

        person = Person(
            tenant_id=ctx.tenant,
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            display_name=f"{payload.first_name.strip()} {payload.last_name.strip()}",
            birth_date=payload.birth_date,
            nationality=payload.nationality,
            email=payload.email,
            source="STAFF_ENTRY",
        )
        self.session.add(person)
        await self.session.flush()

        player = Player(
            tenant_id=ctx.tenant,
            club_id=payload.club_id,
            person_id=person.id,
            status="REGISTERED",
            primary_position=payload.primary_position,
            secondary_positions=payload.secondary_positions,
            preferred_foot=payload.preferred_foot,
            federation_id=payload.federation_id,
            joined_club_on=payload.joined_club_on or date.today(),
        )
        self.session.add(player)
        self.session.add(
            PersonRoleFlag(tenant_id=ctx.tenant, person_id=person.id, role_kind="PLAYER")
        )
        await self.session.flush()

        if payload.team_id is not None and payload.season_id is not None:
            self.session.add(
                PlayerRegistration(
                    tenant_id=ctx.tenant,
                    player_id=player.id,
                    team_id=payload.team_id,
                    season_id=payload.season_id,
                    shirt_number=payload.shirt_number,
                    kind="PERMANENT",
                    registered_on=payload.joined_club_on or date.today(),
                )
            )

        try:
            await self.session.flush()
        except IntegrityError as exc:
            # The database is the authority on uniqueness; the pre-check above
            # is only there to produce a good message in the common case.
            await self.session.rollback()
            raise Conflict("That registration conflicts with an existing one.") from exc

        # Both the event and the audit record are written in this transaction:
        # if the registration rolls back, so do they. Nothing downstream can
        # observe a player that does not exist.
        publish(
            self.session,
            PlayerRegistered.of(
                player.id,
                tenant_id=ctx.tenant,
                club_id=str(payload.club_id),
                team_id=str(payload.team_id) if payload.team_id else None,
            ),
        )
        AuditService(self.session).record(
            ctx,
            action="players.player.create",
            object_type="player",
            object_id=player.id,
            after={
                "status": player.status,
                "club_id": str(player.club_id),
                "primary_position": player.primary_position,
            },
            club_id=payload.club_id,
        )

        log.info(
            "player_created",
            player_id=str(player.id),
            club_id=str(payload.club_id),
            actor=str(ctx.actor_id),
        )
        return await self.get_player(player.id, ScopeFilter(unrestricted=True))

    async def update_player(
        self, player_id: UUID, payload: PlayerUpdate, ctx: RequestContext
    ) -> PlayerDetail:
        player = await self.repo.get_or_404(player_id)

        changes = payload.model_dump(exclude_unset=True)
        # Split by where the column actually lives. The API presents one player;
        # the schema keeps identity on `person` (ADR-0004), and the two stay
        # separate right up to this line.
        person_changes = {
            field: changes.pop(field)
            for field in ("first_name", "last_name", "birth_date", "nationality")
            if field in changes
        }
        before = {field: getattr(player, field) for field in changes}
        previous_status = player.status

        for field, value in changes.items():
            setattr(player, field, value)

        if person_changes:
            person = await self.session.get(Person, player.person_id)
            if person is None:
                raise NotFound(object_type="person", object_id=str(player.person_id))
            before |= {field: getattr(person, field) for field in person_changes}
            for field, value in person_changes.items():
                setattr(person, field, (value.strip() if isinstance(value, str) else value))
            # Kept in step deliberately: display_name is what every list and
            # every match sheet renders, so a corrected surname that leaves it
            # stale has not been corrected at all.
            person.display_name = f"{person.first_name} {person.last_name}"
            changes |= person_changes

        if changes.get("status") == "DEPARTED" and player.left_club_on is None:
            player.left_club_on = date.today()

        AuditService(self.session).record(
            ctx,
            action="players.player.update",
            object_type="player",
            object_id=player.id,
            before=before,
            after=changes,
            club_id=player.club_id,
        )
        if player.status != previous_status:
            publish(
                self.session,
                PlayerStatusChanged.of(
                    player.id,
                    tenant_id=ctx.tenant,
                    from_status=previous_status,
                    to_status=player.status,
                ),
            )

        await self.session.flush()
        log.info(
            "player_updated",
            player_id=str(player_id),
            fields=sorted(changes),
            actor=str(ctx.actor_id),
        )
        return await self.get_player(player_id, ScopeFilter(unrestricted=True))

    async def delete_player(self, player_id: UUID, ctx: RequestContext) -> None:
        """Remove a player, their registrations, and their person if unused.

        Registrations go with the player by foreign key. The person does not:
        the same human may also be on the coaching staff, and deleting a player
        must not delete a coach. So the person is removed only when nothing
        else points at them.
        """
        from app.identity.models import Person, PersonRoleFlag
        from app.teams.models import TeamStaff

        player = await self.repo.get_or_404(player_id)
        person_id = player.person_id
        before = {"display_name": (await self.session.get(Person, person_id)).display_name}

        await self.session.execute(
            delete(PlayerRegistration).where(PlayerRegistration.player_id == player.id)
        )
        club_id = player.club_id
        await self.session.delete(player)
        await self.session.flush()

        still_a_player = await self.session.scalar(
            select(Player.id).where(Player.person_id == person_id).limit(1)
        )
        still_on_staff = await self.session.scalar(
            select(TeamStaff.id).where(TeamStaff.person_id == person_id).limit(1)
        )
        if still_a_player is None and still_on_staff is None:
            await self.session.execute(
                delete(PersonRoleFlag).where(PersonRoleFlag.person_id == person_id)
            )
            person = await self.session.get(Person, person_id)
            if person is not None:
                await self.session.delete(person)

        AuditService(self.session).record(
            ctx,
            action="players.player.delete",
            object_type="player",
            object_id=player_id,
            before=before,
            club_id=club_id,
        )
        await self.session.flush()

    async def change_registration(
        self, player_id: UUID, payload: RegistrationChange, ctx: RequestContext
    ) -> PlayerDetail:
        """Move a player between squads, or change their shirt number.

        The current registration is ended rather than edited: "which team was he
        in last March?" has to stay answerable, and an UPDATE would erase the
        answer. Same reason a shirt change opens a new row — the number on last
        season's team sheet was real.
        """
        player = await self.repo.get_or_404(player_id)

        season_id = payload.season_id or await self._current_season(player.club_id)
        if payload.team_id is not None:
            await self._require_team(payload.team_id, club_id=player.club_id)
            if season_id is None:
                raise ValidationFailed(
                    "This club has no current season, so a player cannot be "
                    "registered to a team yet.",
                    fields=[{"field": "season_id", "code": "NO_CURRENT_SEASON"}],
                )
            if payload.shirt_number is not None and await self.repo.shirt_number_taken(
                payload.team_id, season_id, payload.shirt_number, exclude_player=player_id
            ):
                raise Conflict(
                    f"Shirt number {payload.shirt_number} is already taken in this team.",
                    code_detail="SHIRT_NUMBER_TAKEN",
                    shirt_number=payload.shirt_number,
                )

        current = await self.session.scalar(
            select(PlayerRegistration).where(
                PlayerRegistration.tenant_id == ctx.tenant,
                PlayerRegistration.player_id == player_id,
                PlayerRegistration.ended_on.is_(None),
            )
        )
        today = date.today()
        before: dict[str, Any] = {}
        if current is not None:
            before = {"team_id": str(current.team_id), "shirt_number": current.shirt_number}
            if (
                current.team_id == payload.team_id
                and current.shirt_number == payload.shirt_number
            ):
                return await self.get_player(player_id, ScopeFilter(unrestricted=True))
            current.ended_on = today

        if payload.team_id is not None and season_id is not None:
            self.session.add(
                PlayerRegistration(
                    tenant_id=ctx.tenant,
                    player_id=player_id,
                    team_id=payload.team_id,
                    season_id=season_id,
                    shirt_number=payload.shirt_number,
                    kind="PERMANENT",
                    registered_on=today,
                )
            )

        AuditService(self.session).record(
            ctx,
            action="players.registration.change",
            object_type="player",
            object_id=player_id,
            club_id=player.club_id,
            before=before,
            after={
                "team_id": str(payload.team_id) if payload.team_id else None,
                "shirt_number": payload.shirt_number,
            },
        )

        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise Conflict(
                "That shirt number is already taken in this team.",
                code_detail="SHIRT_NUMBER_TAKEN",
            ) from exc

        log.info("player_registration_changed", player_id=str(player_id))
        return await self.get_player(player_id, ScopeFilter(unrestricted=True))

    # --- helpers -----------------------------------------------------------

    async def _require_club(self, club_id: UUID) -> UUID:
        from app.tenants.models import Club

        exists = await self.session.scalar(
            select(Club.id).where(Club.id == club_id, Club.tenant_id == self.repo.tenant_id)
        )
        if exists is None:
            raise NotFound(object_type="club", object_id=str(club_id))
        return club_id

    async def _require_team(self, team_id: UUID, club_id: UUID) -> None:
        exists = await self.session.scalar(
            select(Team.id).where(
                Team.id == team_id,
                Team.tenant_id == self.repo.tenant_id,
                Team.club_id == club_id,
            )
        )
        if exists is None:
            raise NotFound(object_type="team", object_id=str(team_id))

    async def _current_season(self, club_id: UUID) -> UUID | None:
        return await self.session.scalar(
            select(Season.id).where(
                and_(
                    Season.tenant_id == self.repo.tenant_id,
                    Season.club_id == club_id,
                    Season.is_current.is_(True),
                )
            )
        )


def _to_summary(row: Row[Any]) -> PlayerSummary:
    player, person, team, shirt_number = row
    return PlayerSummary(
        id=player.id,
        person_id=person.id,
        display_name=person.display_name,
        status=player.status,
        primary_position=player.primary_position,
        shirt_number=shirt_number,
        birth_date=person.birth_date.date() if person.birth_date else None,
        team=TeamSummary.model_validate(team) if team is not None else None,
    )


def _to_detail(row: Row[Any]) -> PlayerDetail:
    player, person, team, shirt_number = row
    return PlayerDetail(
        id=player.id,
        person_id=person.id,
        display_name=person.display_name,
        first_name=person.first_name,
        last_name=person.last_name,
        status=player.status,
        primary_position=player.primary_position,
        secondary_positions=list(player.secondary_positions or []),
        preferred_foot=player.preferred_foot,
        nationality=list(person.nationality or []),
        federation_id=player.federation_id,
        joined_club_on=player.joined_club_on,
        left_club_on=player.left_club_on,
        club_id=player.club_id,
        shirt_number=shirt_number,
        birth_date=person.birth_date.date() if person.birth_date else None,
        team=TeamSummary.model_validate(team) if team is not None else None,
        created_at=player.created_at,
        updated_at=player.updated_at,
    )
