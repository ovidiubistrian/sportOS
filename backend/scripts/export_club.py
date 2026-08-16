"""Export one club's news and squad to a file.

    python scripts/export_club.py --slug csm-resita --out /tmp/csm.json

Written for moving a club from a development database to a real one, which is
a thing that happens exactly once per club and is miserable by hand: 112
players is not something anybody retypes.

What it takes: the club's news (categories, articles and every translation)
and its squad (people, players, registrations). What it deliberately does not
take, and why:

  media       Object storage is a second system with its own credentials, and
              the source objects are usually on a laptop the target cannot
              reach. References are exported so the importer can say what it
              dropped, but the pictures are re-uploaded by hand.
  users       A login lives in Keycloak. Its subject id means nothing in
              another realm, so a copied role assignment would point at an
              account that cannot sign in. Staff are re-invited.
  ids         Nothing is exported by primary key. Teams travel by `code`,
              seasons by `name`, categories by `key` — the things a human
              chose, which are stable across databases in a way UUIDs are not.

The output is JSON, readable, and safe to look at before importing: this is
somebody's club, and a migration you cannot inspect is a migration you cannot
trust.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.cms.models import ContentCategory, ContentItem, ContentTranslation
from app.core.db import platform_session
from app.core.model_registry import *  # noqa: F403
from app.identity.models import Person, PersonRoleFlag
from app.players.models import Player, PlayerRegistration
from app.teams.models import Season, Team
from app.tenants.models import Club

# Columns every table has and nothing may carry across: the identity of a row
# in *this* database, and when it was written here.
SKIP = {"id", "tenant_id", "club_id", "created_at", "updated_at"}


def _plain(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _row(obj: Any, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every column except the ones that identify the row here."""
    out = {
        column.name: _plain(getattr(obj, column.name))
        for column in obj.__table__.columns
        if column.name not in SKIP
    }
    out.update(extra or {})
    return out


async def export(slug: str) -> dict[str, Any]:
    async with platform_session(reason=f"export club {slug}", routine=True) as session:
        club = await session.scalar(select(Club).where(Club.slug == slug))
        if club is None:
            sys.exit(f"No club with slug {slug!r}.")

        # Lookups from id back to the human-chosen name, so the importer can
        # find the equivalent row in a database that numbers things differently.
        teams = {
            team.id: team.code
            for team in await session.scalars(select(Team).where(Team.club_id == club.id))
        }
        seasons = {
            season.id: season.name
            for season in await session.scalars(select(Season).where(Season.club_id == club.id))
        }
        categories = {
            category.id: category.key
            for category in await session.scalars(
                select(ContentCategory).where(ContentCategory.club_id == club.id)
            )
        }

        # --- news ---------------------------------------------------------
        items = list(
            await session.scalars(select(ContentItem).where(ContentItem.club_id == club.id))
        )
        translations: dict[UUID, list[Any]] = {}
        for translation in await session.scalars(
            select(ContentTranslation).where(ContentTranslation.club_id == club.id)
        ):
            translations.setdefault(translation.content_item_id, []).append(translation)

        news = [
            {
                **_row(item, extra={"category": categories.get(item.category_id)}),
                "category_id": None,
                "translations": [
                    _row(t, extra={"content_item_id": None})
                    for t in translations.get(item.id, [])
                ],
            }
            for item in items
        ]

        # --- squad ----------------------------------------------------------
        people = list(
            await session.scalars(select(Person).where(Person.tenant_id == club.tenant_id))
        )
        by_person = {person.id: person for person in people}

        flags: dict[UUID, list[str]] = {}
        for flag in await session.scalars(
            select(PersonRoleFlag).where(PersonRoleFlag.tenant_id == club.tenant_id)
        ):
            flags.setdefault(flag.person_id, []).append(flag.role_kind)

        players = list(await session.scalars(select(Player).where(Player.club_id == club.id)))
        player_ids = {player.id for player in players}
        # A registration belongs to a team, not to a club — a player's club is
        # whichever club owns the team they are registered with. So these are
        # collected by player rather than filtered by club_id, which the table
        # does not carry.
        registrations: dict[UUID, list[Any]] = {}
        for registration in await session.scalars(
            select(PlayerRegistration).where(PlayerRegistration.player_id.in_(player_ids))
        ):
            registrations.setdefault(registration.player_id, []).append(registration)

        squad = []
        for player in players:
            person = by_person.get(player.person_id)
            if person is None:
                continue
            squad.append(
                {
                    "person": _row(person, extra={"user_id": None}),
                    "role_flags": sorted(set(flags.get(person.id, ["PLAYER"]))),
                    "player": _row(player, extra={"person_id": None, "photo_media_id": None}),
                    "registrations": [
                        _row(
                            registration,
                            extra={
                                "player_id": None,
                                "team": teams.get(registration.team_id),
                                "season": seasons.get(registration.season_id),
                                "team_id": None,
                                "season_id": None,
                            },
                        )
                        for registration in registrations.get(player.id, [])
                    ],
                }
            )

        dropped_photos = sum(1 for player in players if player.photo_media_id)

        return {
            "format": 1,
            "club": {"slug": club.slug, "display_name": club.display_name},
            "categories": [
                _row(category)
                for category in await session.scalars(
                    select(ContentCategory).where(ContentCategory.club_id == club.id)
                )
            ],
            "news": news,
            "squad": squad,
            "notes": {
                "photos_not_exported": dropped_photos,
                "media": "Pictures are not carried. Re-upload them in the target.",
            },
        }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, help="the club's slug in this database")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    payload = await export(args.slug)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print(f"club        {payload['club']['display_name']}")
    print(f"categories  {len(payload['categories'])}")
    print(f"news        {len(payload['news'])}")
    print(f"squad       {len(payload['squad'])}")
    if payload["notes"]["photos_not_exported"]:
        print(f"photos      {payload['notes']['photos_not_exported']} not carried — re-upload")
    print(f"written     {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
