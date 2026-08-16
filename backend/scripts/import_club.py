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

        existing_people = {
            (person.first_name, person.last_name, person.birth_date)
            for person in await session.scalars(
                select(Person).where(Person.tenant_id == club.tenant_id)
            )
        }

        for entry in payload.get("squad", []):
            person_row = entry["person"]
            identity = (
                person_row["first_name"],
                person_row["last_name"],
                _typed("birth_date", person_row.get("birth_date")),
            )
            if identity in existing_people:
                report.did("players skipped")
                continue

            person = Person(
                id=new_id(),
                tenant_id=club.tenant_id,
                **_fields(person_row, Person, user_id=None),
            )
            session.add(person)
            await session.flush()
            existing_people.add(identity)

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
    args = parser.parse_args()

    payload = json.loads(args.file.read_text())
    if payload.get("format") != 1:
        sys.exit(f"Unknown export format {payload.get('format')!r}.")

    print(f"from  {payload['club']['display_name']} ({payload['club']['slug']})")
    print(f"into  {args.slug}\n")

    report = await run(payload, args.slug, args.dry_run)
    report.print()

    if payload["notes"]["photos_not_exported"]:
        print(
            f"\n{payload['notes']['photos_not_exported']} photographs were not carried. "
            "Upload them again in the target."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
