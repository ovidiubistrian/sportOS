"""Bring in the provider's squad for one team, from the command line.

    python scripts/import_squad.py --slug csm-resita --team SEN --dry-run
    python scripts/import_squad.py --slug csm-resita --team SEN

The same work the admin's Import button does, for a server that has the button
in a release it has not deployed yet. Takes the club by slug and the team by
code, because those are what a person knows without opening a database.

Reads the provider team id from the club's feed, so the club must be connected
first — there is no way to point this at an arbitrary team, which is
deliberate: the whole risk in this feature is somebody else's squad arriving.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.db import platform_session
from app.core.model_registry import *  # noqa: F403
from app.integrations.api_football import squads
from app.integrations.api_football.client import ApiFootball
from app.integrations.models import ClubFeed
from app.teams.models import Season, Team
from app.tenants.models import Club


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, help="the club's slug")
    parser.add_argument("--team", required=True, help="the team's code, e.g. SEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    async with platform_session(reason=f"import squad for {args.slug}") as session:
        club = await session.scalar(select(Club).where(Club.slug == args.slug))
        if club is None:
            sys.exit(f"No club with slug {args.slug!r}.")

        team = await session.scalar(
            select(Team).where(Team.club_id == club.id, Team.code == args.team.upper())
        )
        if team is None:
            codes = [
                row.code
                for row in await session.scalars(select(Team).where(Team.club_id == club.id))
            ]
            sys.exit(f"No team {args.team!r}. This club has: {', '.join(codes) or 'none'}.")

        season = await session.scalar(
            select(Season).where(Season.club_id == club.id, Season.is_current.is_(True))
        )
        if season is None:
            sys.exit("This club has no current season, and a registration needs one.")

        feed = await session.scalar(
            select(ClubFeed).where(
                ClubFeed.club_id == club.id, ClubFeed.provider == "API_FOOTBALL"
            )
        )
        if feed is None or not feed.provider_team_id:
            sys.exit("This club is not connected to the results feed yet.")

        print(f"club    {club.display_name}")
        print(f"team    {team.name} ({team.code})")
        print(f"season  {season.name}")
        print(f"feed    {feed.provider_team_name} (#{feed.provider_team_id})\n")

        async with ApiFootball() as client:
            result = await squads.import_squad(
                session,
                client,
                tenant_id=club.tenant_id,
                club_id=club.id,
                team_id=team.id,
                season_id=season.id,
                provider_team_id=feed.provider_team_id,
            )

        for note in result.notes:
            print(" ", note)
        print(f"\ncreated  {result.created}")
        print(f"skipped  {result.skipped}  (already in the squad)")

        if args.dry_run:
            await session.rollback()
            print("\nDRY RUN — nothing was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
