"""Import a squad from the provider.

The provider knows who plays for a linked club — names, shirt numbers and a
broad position each. That is most of what a club retypes every transfer window,
and none of it is a judgement call, so it is worth fetching.

Three things it deliberately does not take:

`photographs`   Pictures of identifiable people, from a third party, published
                on a club's website. The club's right to publish its own
                players is clear; our right to redistribute a data provider's
                images is not, and at a club with an academy that is not a
                question to answer casually. A club uploads its own, and knows
                what it is publishing and who agreed to it.
`dates of birth`  The provider gives an age, not a date, and a date computed
                from an age is wrong for most of the year — in a field that
                decides which age group a child may play in.
`who to remove` A player missing from the provider's list has not necessarily
                left: the provider lags transfers by weeks. Departures are the
                club's to record.

Matching is by name and shirt number together, and creates nothing it is not
sure about — the failure to avoid is a squad of a hundred where every player
appears twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.identity.models import Person, PersonRoleFlag
from app.integrations.api_football.autolink import fold
from app.integrations.api_football.client import ApiFootball
from app.players.models import Player, PlayerRegistration

log = structlog.get_logger(__name__)

# The provider reports one of four broad positions. Ours are specific, so this
# maps to the least committal member of each group: a defender becomes a centre
# back, which is wrong for a full back and easy for the club to correct — where
# guessing at a side would be wrong half the time and look deliberate.
_POSITIONS = {
    "goalkeeper": "GK",
    "defender": "CB",
    "midfielder": "CM",
    "attacker": "ST",
}


@dataclass
class SquadResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    coach: str | None = None
    notes: list[str] = field(default_factory=list)


def split_name(full: str) -> tuple[str, str]:
    """A provider's single name field into ours.

    Everything before the last space is the given name. Wrong for compound
    surnames — "Popa de Vale" — and right for the overwhelming majority; the
    club can fix the rest in one edit, which is cheaper than the alternative of
    refusing to import anyone whose name has three parts.
    """
    parts = [part for part in (full or "").split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return " ".join(parts[:-1]), parts[-1]


async def import_squad(
    session: AsyncSession,
    client: ApiFootball,
    *,
    tenant_id: UUID,
    club_id: UUID,
    team_id: UUID,
    season_id: UUID,
    provider_team_id: str,
) -> SquadResult:
    """Fetch the provider's squad and add whoever is missing from ours."""
    result = SquadResult()
    payload = await client.squad(team=provider_team_id)
    rows = (payload[0].get("players") or []) if payload else []
    if not rows:
        result.notes.append("The provider lists nobody for this club.")
        return result

    # Everyone already at the club, by folded name. Folding matters because a
    # provider writes "Stefan Popa" where the club wrote "Ștefan Popa", and
    # importing the same player twice under two spellings is the outcome most
    # worth preventing.
    existing: dict[str, Player] = {}
    people = await session.execute(
        select(Person, Player)
        .join(Player, Player.person_id == Person.id)
        .where(Player.club_id == club_id)
    )
    for person, player in people:
        existing[fold(person.display_name)] = player

    worn = {
        registration.shirt_number
        for registration in await session.scalars(
            select(PlayerRegistration).where(
                PlayerRegistration.team_id == team_id,
                PlayerRegistration.season_id == season_id,
                PlayerRegistration.ended_on.is_(None),
            )
        )
        if registration.shirt_number is not None
    }

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        first, last = split_name(name)
        key = fold(f"{first} {last}")

        if key in existing:
            result.skipped += 1
            continue

        person = Person(
            id=new_id(),
            tenant_id=tenant_id,
            first_name=first,
            last_name=last,
            display_name=f"{first} {last}",
            nationality=[],
        )
        session.add(person)
        await session.flush()
        session.add(
            PersonRoleFlag(tenant_id=tenant_id, person_id=person.id, role_kind="PLAYER")
        )

        player = Player(
            id=new_id(),
            tenant_id=tenant_id,
            club_id=club_id,
            person_id=person.id,
            primary_position=_POSITIONS.get((row.get("position") or "").lower()),
            secondary_positions=[],
            status="REGISTERED",
        )
        session.add(player)
        await session.flush()

        shirt = row.get("number")
        if shirt is not None and shirt in worn:
            result.notes.append(f"{person.display_name}: number {shirt} is taken here")
            shirt = None
        elif shirt is not None:
            worn.add(shirt)

        session.add(
            PlayerRegistration(
                id=new_id(),
                tenant_id=tenant_id,
                player_id=player.id,
                team_id=team_id,
                season_id=season_id,
                shirt_number=shirt,
                kind="PERMANENT",
                # Today, not the day the provider says they signed: we do not
                # know that, and a registration dated before the season began
                # would put the player in a squad they were not in.
                registered_on=date.today(),
            )
        )
        existing[key] = player
        result.created += 1

    result.coach = await _import_coach(
        session,
        client,
        tenant_id=tenant_id,
        club_id=club_id,
        team_id=team_id,
        provider_team_id=provider_team_id,
        result=result,
    )

    log.info(
        "squad_imported",
        club_id=str(club_id),
        team_id=str(team_id),
        created=result.created,
        skipped=result.skipped,
    )
    return result


async def _import_coach(
    session: AsyncSession,
    client: ApiFootball,
    *,
    tenant_id: UUID,
    club_id: UUID,
    team_id: UUID,
    provider_team_id: str,
    result: SquadResult,
) -> str | None:
    """Add the head coach, if this team has none and the provider knows one.

    Only the head coach: assistants, goalkeeping coaches and physios are not in
    a results provider's catalogue, because they are not part of a result.
    Those stay the club's to enter, which is also where the club's own words
    for the jobs belong.

    Never replaces a coach the club has entered. A club knows who is in charge
    of its team better than a catalogue that lags a change by weeks, and the
    week it lags is exactly the week somebody looks.
    """
    from app.teams.models import TeamStaff

    already = await session.scalar(
        select(TeamStaff).where(TeamStaff.team_id == team_id, TeamStaff.role == "HEAD_COACH")
    )
    if already is not None:
        return None

    try:
        rows = await client.coaches(team=provider_team_id)
    except Exception:
        # A squad that arrived is worth keeping even when this does not.
        log.info("coach_lookup_failed", club_id=str(club_id))
        return None

    current = next(
        (
            row
            for row in rows
            if row.get("name") and not (row.get("career") or [{}])[0].get("end")
        ),
        rows[0] if rows else None,
    )
    if current is None or not current.get("name"):
        result.notes.append("The provider does not list a coach for this club.")
        return None

    first, last = split_name(str(current["name"]))
    person = Person(
        id=new_id(),
        tenant_id=tenant_id,
        first_name=first,
        last_name=last,
        display_name=f"{first} {last}",
        nationality=[],
    )
    session.add(person)
    await session.flush()
    session.add(PersonRoleFlag(tenant_id=tenant_id, person_id=person.id, role_kind="STAFF"))
    session.add(
        TeamStaff(
            id=new_id(),
            tenant_id=tenant_id,
            club_id=club_id,
            team_id=team_id,
            person_id=person.id,
            role="HEAD_COACH",
            is_public=True,
        )
    )
    await session.flush()
    log.info("coach_imported", club_id=str(club_id), name=person.display_name)
    return person.display_name
