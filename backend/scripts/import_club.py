"""Import a club's news and squad from a file written by export_club.py.

    python scripts/import_club.py --file /tmp/csm.json --slug csm-resita --dry-run
    python scripts/import_club.py --file /tmp/csm.json --slug csm-resita

Runs against a *different* database than the export: that is the whole point.
Nothing arrives with its old primary key. Teams are matched by `code`, seasons
by `name`, categories by `key` — the names a human chose, which mean the same
thing in both databases where a UUID does not.

Idempotent by refusal rather than by merge. An article whose slug already
exists is skipped, and a person with the same name and date of birth is
skipped. That is the conservative reading: importing twice should cost nothing,
and a second import is far more likely to be a mistake than an intention. What
it skips it says out loud.

`--dry-run` reports exactly what would happen and writes nothing. Use it. This
is somebody's club.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.cms.models import ContentCategory, ContentItem, ContentTranslation
from app.core.db import platform_session
from app.core.ids import new_id
from app.core.model_registry import *  # noqa: F403
from app.identity.models import Person, PersonRoleFlag
from app.players.models import Player, PlayerRegistration
from app.teams.models import Season, Team
from app.tenants.models import Club

# Columns whose value is a timestamp or a date in the file and a typed column
# in the database. Everything else survives a round trip as-is.
_DATE_FIELDS = {
    "birth_date",
    "joined_club_on",
    "left_club_on",
    "registered_on",
    "ended_on",
    "published_at",
    "scheduled_for",
    "start_date",
    "end_date",
}


def _typed(field: str, value: Any) -> Any:
    if value is None or field not in _DATE_FIELDS or not isinstance(value, str):
        return value
    parsed = datetime.fromisoformat(value)
    # A date column will not take a datetime, and vice versa. The column knows
    # which it wants; the file only knows it was one of the two.
    return parsed if "T" in value else parsed.date()


def _fields(row: dict[str, Any], model: Any, **overrides: Any) -> dict[str, Any]:
    """The subset of a file row that this model actually has columns for."""
    names = {column.name for column in model.__table__.columns}
    out = {
        key: _typed(key, value)
        for key, value in row.items()
        if (key in names and not isinstance(value, list | dict)) or key in {"nationality"}
    }
    out.update(overrides)
    return out


class Report:
    def __init__(self, dry: bool) -> None:
        self.dry = dry
        self.lines: list[str] = []
        self.counts: dict[str, int] = {}

    def did(self, what: str) -> None:
        self.counts[what] = self.counts.get(what, 0) + 1

    def note(self, line: str) -> None:
        self.lines.append(line)

    def print(self) -> None:
        for line in self.lines[:40]:
            print(" ", line)
        if len(self.lines) > 40:
            print(f"  … and {len(self.lines) - 40} more")
        print()
        for what, count in sorted(self.counts.items()):
            print(f"{what:<24} {count}")
        if self.dry:
            print("\nDRY RUN — nothing was written.")


async def link_registrations(payload: dict[str, Any], slug: str, dry: bool) -> Report:
    """Attach squads to players who are already here.

    The repair for an import run before the teams existed: the people landed,
    every registration was skipped, and running the import again would not fix
    it — it would add a second hundred players, because a person with no date
    of birth cannot be recognised as one we already have.

    Players are matched by display name within the club, which is safe here in
    a way it is not for creation: we are attaching a squad to somebody who
    demonstrably exists, and a name that matches two people is reported rather
    than guessed at.
    """
    report = Report(dry)

    async with platform_session(reason=f"link registrations {slug}") as session:
        club = await session.scalar(select(Club).where(Club.slug == slug))
        if club is None:
            sys.exit(f"No club with slug {slug!r} in this database.")

        teams = {
            team.code: team.id
            for team in await session.scalars(select(Team).where(Team.club_id == club.id))
        }
        seasons = {
            season.name: season.id
            for season in await session.scalars(select(Season).where(Season.club_id == club.id))
        }
        if not teams or not seasons:
            sys.exit(
                "This club has no teams or no seasons yet. Create them first — "
                "a registration needs both, and the codes have to match the export."
            )

        # display name -> the players who have it, oldest first.
        #
        # Thirty of a hundred names are shared in a squad this size, so
        # refusing every repeat would leave a third of the club without a team.
        # They are paired by order instead: the import created them in file
        # order, so the second "Alexandru Marin" in the file is the second one
        # in the database. That holds because this repairs an import that has
        # just happened; where the count does not match, the extras are left
        # alone rather than assigned to whoever is nearest.
        candidates: dict[str, list[Any]] = {}
        rows = await session.execute(
            select(Person.display_name, Player.id)
            .join(Player, Player.person_id == Person.id)
            .where(Player.club_id == club.id)
            .order_by(Player.created_at, Player.id)
        )
        for display_name, player_id in rows:
            candidates.setdefault(display_name, []).append(player_id)

        seen: dict[str, int] = {}

        worn = {
            (registration.team_id, registration.season_id, registration.shirt_number)
            for registration in await session.scalars(
                select(PlayerRegistration).where(
                    PlayerRegistration.tenant_id == club.tenant_id,
                    PlayerRegistration.ended_on.is_(None),
                )
            )
        }
        registered = {
            (registration.player_id, registration.team_id, registration.season_id)
            for registration in await session.scalars(
                select(PlayerRegistration).where(PlayerRegistration.tenant_id == club.tenant_id)
            )
        }

        for entry in payload.get("squad", []):
            name = entry["person"]["display_name"]
            position = seen.get(name, 0)
            seen[name] = position + 1
            here = candidates.get(name, [])
            if position >= len(here):
                report.note(
                    f"{name}: not in this club"
                    if not here
                    else f"{name}: the file has more of this name than the club does"
                )
                report.did("players not found")
                continue
            player_id = here[position]
            if len(here) > 1:
                report.did("shared names paired by order")

            for registration in entry.get("registrations", []):
                team_id = teams.get(registration.get("team") or "")
                season_id = seasons.get(registration.get("season") or "")
                if team_id is None or season_id is None:
                    missing = []
                    if team_id is None:
                        missing.append(f"team {registration.get('team')!r}")
                    if season_id is None:
                        missing.append(f"season {registration.get('season')!r}")
                    report.note(f"{name}: no {' and no '.join(missing)}")
                    report.did("registrations skipped")
                    continue
                if (player_id, team_id, season_id) in registered:
                    report.did("registrations already here")
                    continue

                shirt = registration.get("shirt_number")
                if shirt is not None and (team_id, season_id, shirt) in worn:
                    report.note(f"{name}: number {shirt} already worn, registered without one")
                    registration = {**registration, "shirt_number": None}
                    report.did("shirt numbers dropped")
                elif shirt is not None:
                    worn.add((team_id, season_id, shirt))

                session.add(
                    PlayerRegistration(
                        id=new_id(),
                        tenant_id=club.tenant_id,
                        **_fields(
                            registration,
                            PlayerRegistration,
                            player_id=player_id,
                            team_id=team_id,
                            season_id=season_id,
                        ),
                    )
                )
                registered.add((player_id, team_id, season_id))
                report.did("registrations created")

        if dry:
            await session.rollback()

    return report


async def run(payload: dict[str, Any], slug: str, dry: bool) -> Report:
    report = Report(dry)

    async with platform_session(reason=f"import club {slug}") as session:
        club = await session.scalar(select(Club).where(Club.slug == slug))
        if club is None:
            sys.exit(f"No club with slug {slug!r} in this database.")

        teams = {
            team.code: team.id
            for team in await session.scalars(select(Team).where(Team.club_id == club.id))
        }
        seasons = {
            season.name: season.id
            for season in await session.scalars(select(Season).where(Season.club_id == club.id))
        }
        categories = {
            category.key: category.id
            for category in await session.scalars(
                select(ContentCategory).where(ContentCategory.club_id == club.id)
            )
        }

        # --- categories -----------------------------------------------------
        for row in payload.get("categories", []):
            if row["key"] in categories:
                continue
            category = ContentCategory(
                id=new_id(),
                tenant_id=club.tenant_id,
                club_id=club.id,
                **_fields(row, ContentCategory),
            )
            session.add(category)
            await session.flush()
            categories[row["key"]] = category.id
            report.did("categories created")

        # --- news -----------------------------------------------------------
        taken = {
            (translation.locale, translation.slug)
            for translation in await session.scalars(
                select(ContentTranslation).where(ContentTranslation.club_id == club.id)
            )
        }

        for row in payload.get("news", []):
            slugs = {(t["locale"], t["slug"]) for t in row["translations"]}
            if slugs & taken:
                report.note(f"news already here: {row['translations'][0]['title']}")
                report.did("news skipped")
                continue

            item = ContentItem(
                id=new_id(),
                tenant_id=club.tenant_id,
                club_id=club.id,
                **_fields(
                    row,
                    ContentItem,
                    category_id=categories.get(row.get("category") or ""),
                    # An author and a cover live in the source database. The
                    # person is not here and the picture is not carried, so the
                    # article arrives without either rather than pointing at a
                    # row that does not exist.
                    author_person_id=None,
                    created_by=None,
                    cover_media_id=None,
                ),
            )
            session.add(item)
            await session.flush()

            for translation in row["translations"]:
                session.add(
                    ContentTranslation(
                        id=new_id(),
                        tenant_id=club.tenant_id,
                        club_id=club.id,
                        **_fields(translation, ContentTranslation, content_item_id=item.id),
                    )
                )
            taken |= slugs
            report.did("news created")

        # --- squad ------------------------------------------------------------
        # One shirt number per team per season is a database constraint, and a
        # club importing into a squad that is not empty will collide. Better to
        # land the player without the number and say so than to stop halfway
        # through 112 of them.
        worn = {
            (registration.team_id, registration.season_id, registration.shirt_number)
            for registration in await session.scalars(
                select(PlayerRegistration).where(
                    PlayerRegistration.tenant_id == club.tenant_id,
                    PlayerRegistration.ended_on.is_(None),
                )
            )
        }

        # Only people we can actually recognise again. A name alone is not an
        # identity: among a hundred players two will share one, and with no
        # date of birth recorded the second would be silently dropped as a
        # duplicate of the first. So a person counts as already here only when
        # something distinguishing matches — a birth date, or the federation
        # id, which is exactly what a federation id is for.
        existing_people: set[tuple[str, str, Any]] = set()
        for person in await session.scalars(
            select(Person).where(Person.tenant_id == club.tenant_id)
        ):
            if person.birth_date is not None:
                existing_people.add((person.first_name, person.last_name, person.birth_date))

        registered_ids = {
            player.federation_id
            for player in await session.scalars(
                select(Player).where(
                    Player.club_id == club.id, Player.federation_id.isnot(None)
                )
            )
        }

        for entry in payload.get("squad", []):
            person_row = entry["person"]
            born = _typed("birth_date", person_row.get("birth_date"))
            identity = (person_row["first_name"], person_row["last_name"], born)
            federation_id = entry["player"].get("federation_id")

            already = (born is not None and identity in existing_people) or (
                federation_id is not None and federation_id in registered_ids
            )
            if already:
                report.note(f"already here: {person_row['display_name']}")
                report.did("players skipped")
                continue

            person = Person(
                id=new_id(),
                tenant_id=club.tenant_id,
                **_fields(person_row, Person, user_id=None),
            )
            session.add(person)
            await session.flush()
            if born is not None:
                existing_people.add(identity)
            if federation_id is not None:
                registered_ids.add(federation_id)

            for kind in entry.get("role_flags") or ["PLAYER"]:
                session.add(
                    PersonRoleFlag(
                        tenant_id=club.tenant_id, person_id=person.id, role_kind=kind
                    )
                )

            player = Player(
                id=new_id(),
                tenant_id=club.tenant_id,
                club_id=club.id,
                **_fields(entry["player"], Player, person_id=person.id, photo_media_id=None),
            )
            session.add(player)
            await session.flush()
            report.did("players created")

            for registration in entry.get("registrations", []):
                team_id = teams.get(registration.get("team") or "")
                season_id = seasons.get(registration.get("season") or "")
                if team_id is None or season_id is None:
                    missing = []
                    if team_id is None:
                        missing.append(f"team {registration.get('team')!r}")
                    if season_id is None:
                        missing.append(f"season {registration.get('season')!r}")
                    report.note(f"{person.display_name}: no {' and no '.join(missing)}")
                    report.did("registrations skipped")
                    continue

                shirt = registration.get("shirt_number")
                if shirt is not None and (team_id, season_id, shirt) in worn:
                    report.note(
                        f"{person.display_name}: number {shirt} already worn in "
                        f"{registration.get('team')}, registered without one"
                    )
                    registration = {**registration, "shirt_number": None}
                    report.did("shirt numbers dropped")
                elif shirt is not None:
                    worn.add((team_id, season_id, shirt))

                session.add(
                    PlayerRegistration(
                        id=new_id(),
                        tenant_id=club.tenant_id,
                        **_fields(
                            registration,
                            PlayerRegistration,
                            player_id=player.id,
                            team_id=team_id,
                            season_id=season_id,
                        ),
                    )
                )
                report.did("registrations created")

        if dry:
            await session.rollback()

    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--slug", required=True, help="the club's slug in THIS database")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--registrations-only",
        action="store_true",
        help="attach squads to players already here, creating nobody",
    )
    args = parser.parse_args()

    payload = json.loads(args.file.read_text())
    if payload.get("format") != 1:
        sys.exit(f"Unknown export format {payload.get('format')!r}.")

    print(f"from  {payload['club']['display_name']} ({payload['club']['slug']})")
    print(f"into  {args.slug}\n")

    report = await (
        link_registrations(payload, args.slug, args.dry_run)
        if args.registrations_only
        else run(payload, args.slug, args.dry_run)
    )
    report.print()

    if payload["notes"]["photos_not_exported"]:
        print(
            f"\n{payload['notes']['photos_not_exported']} photographs were not carried. "
            "Upload them again in the target."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
