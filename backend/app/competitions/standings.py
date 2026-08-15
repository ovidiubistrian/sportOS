"""League tables, computed from results.

Never stored. A table is a pure function of the matches played plus whatever
points adjustments the competition has handed out, and the moment it becomes a
column somebody can edit, it diverges from the fixtures underneath it — usually
in the week a result is corrected.

Recomputing is cheap at this scale: a division is twenty clubs and about four
hundred matches a season, which is one indexed query and a fold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.competitions.models import (
    CompetitionEntry,
    CompetitionSeason,
    DirectoryClub,
    Match,
)


@dataclass(slots=True)
class TableRow:
    club_id: UUID
    club_name: str
    club_short_name: str
    crest_url: str | None
    group_label: str | None

    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    adjustment: int = 0
    # Most recent results first: W/D/L, at most five. Supporters read the run
    # before they read the points.
    form: list[str] = field(default_factory=list)

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def points(self) -> int:
        return self.base_points + self.adjustment

    base_points: int = 0


async def compute_table(session: AsyncSession, competition_season_id: UUID) -> list[TableRow]:
    """The table for one season of one competition.

    Only played matches count. A postponed fixture is not a nil-nil, and a
    cancelled one never happened — which is why the status drives this rather
    than the presence of a score.
    """
    season = await session.get(CompetitionSeason, competition_season_id)
    if season is None:
        return []

    entries = (
        await session.execute(
            select(CompetitionEntry, DirectoryClub)
            .join(DirectoryClub, DirectoryClub.id == CompetitionEntry.directory_club_id)
            .where(CompetitionEntry.competition_season_id == competition_season_id)
        )
    ).all()

    rows: dict[UUID, TableRow] = {
        club.id: TableRow(
            club_id=club.id,
            club_name=club.name,
            club_short_name=club.short_name,
            crest_url=club.crest_url,
            group_label=entry.group_label,
            adjustment=entry.points_adjustment,
        )
        for entry, club in entries
    }

    matches = await session.scalars(
        select(Match)
        .where(
            Match.competition_season_id == competition_season_id,
            Match.status.in_(("FINISHED", "AWARDED")),
        )
        .order_by(Match.kickoff_at)
    )

    for match in matches:
        home = rows.get(match.home_club_id)
        away = rows.get(match.away_club_id)
        if home is None or away is None or match.home_score is None or match.away_score is None:
            # A result against a club that is not in this season's entry list is
            # a data error, not a table row. Skipping it keeps the table honest
            # and leaves the bad fixture visible where it can be fixed.
            continue

        home.played += 1
        away.played += 1
        home.goals_for += match.home_score
        home.goals_against += match.away_score
        away.goals_for += match.away_score
        away.goals_against += match.home_score

        if match.home_score > match.away_score:
            home.won += 1
            away.lost += 1
            home.base_points += season.points_for_win
            home.form.append("W")
            away.form.append("L")
        elif match.home_score < match.away_score:
            away.won += 1
            home.lost += 1
            away.base_points += season.points_for_win
            away.form.append("W")
            home.form.append("L")
        else:
            home.drawn += 1
            away.drawn += 1
            home.base_points += season.points_for_draw
            away.base_points += season.points_for_draw
            home.form.append("D")
            away.form.append("D")

    for row in rows.values():
        # Newest first, capped — a full season of letters is not form, it is a
        # wall.
        row.form = list(reversed(row.form))[:5]

    # Points, then goal difference, then goals scored, then name. The last one
    # is not a real tiebreaker in any federation's rules, but a table has to be
    # in *some* deterministic order or it reshuffles on every request.
    return sorted(
        rows.values(),
        key=lambda r: (-r.points, -r.goal_difference, -r.goals_for, r.club_name),
    )
