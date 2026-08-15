"""Competitions, fixtures and results.

Everything in this module is **platform reference data**, not tenant data, and
that is the decision the whole design rests on.

A match between two clubs is one event, not two. If each tenant kept its own
copy, the same fixture would exist twice with two kick-off times and two
scorelines, a league table could never be computed, and two customer clubs in
the same division would never see each other. So competitions, the club
directory and matches are global; a tenant reaches them through the directory
entry its own club is linked to.

The structure is country-first so a second country is rows, not a refactor:

    country ─── competition ─── competition_season ─── entry
                    │                    │
                 format               match

`format` is what makes one model serve a league, a domestic cup and a European
competition. A league has numbered matchdays; a cup has named stages; Europe has
groups and then stages. One free-text "round" column would be wrong for all
three, so the round is a *kind* plus a number plus a label.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, GlobalModel, Timestamped, UUIDPrimaryKey
from app.sports.registry import ALL_EVENT_KINDS

# How a competition is played. Decides what a "round" means and whether a table
# can be computed at all.
COMPETITION_FORMATS = ("LEAGUE", "KNOCKOUT", "GROUP_KNOCKOUT")

# Where a competition sits. Domestic tiers are 1..n within a country;
# continental competitions have no tier because they cut across them.
COMPETITION_SCOPES = ("DOMESTIC_LEAGUE", "DOMESTIC_CUP", "CONTINENTAL", "FRIENDLY")

ROUND_KINDS = ("MATCHDAY", "STAGE", "GROUP")

# Who owns the row. A club may edit what it entered; a fixture that arrives
# from a provider is kept in step by sync, and letting both write it means the
# next sync silently reverts whatever the club just corrected.
MATCH_SOURCES = ("CLUB", "API_FOOTBALL")

# What happened, at the level a supporter cares about. Deliberately coarse:
# the provider distinguishes a dozen kinds of VAR decision, and a match report
# that lists them all is a log rather than a story.
# Every kind any sport we support can produce. The narrower question — which
# of these mean anything for *this* match — is answered by the sport profile,
# because a database constraint cannot know what sport a row belongs to
# without a join it should not be doing.
EVENT_KINDS = ALL_EVENT_KINDS

MATCH_STATUSES = (
    "SCHEDULED",
    "LIVE",
    "FINISHED",
    "POSTPONED",
    "CANCELLED",
    "AWARDED",  # decided off the pitch — forfeit, withdrawal
)


class Country(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A football country.

    The root of the pyramid. Adding Bulgaria is this row plus its competitions;
    nothing in the application branches on which country it is.
    """

    __tablename__ = "country"
    __table_args__ = (
        UniqueConstraint("code", name="uq_country_code"),
        CheckConstraint("length(code) = 2", name="country_code_is_alpha2"),
    )

    # ISO 3166-1 alpha-2, so it joins to the tenant's own country.
    code: Mapped[str] = mapped_column(String(2))
    name: Mapped[str] = mapped_column(String(120))
    # In the country's own language: a Romanian reader looks for "România".
    endonym: Mapped[str | None] = mapped_column(String(120))


class Competition(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A named competition, independent of any one season.

    Liga 2 is one competition with many seasons. Keeping the identity separate
    from the season is what lets a club's history say "we were in Liga 2 in
    2019 and Liga 3 in 2021" without either row being rewritten.
    """

    __tablename__ = "competition"
    __table_args__ = (
        UniqueConstraint("country_id", "key", name="uq_competition_key"),
        CheckConstraint(
            "format IN " + str(COMPETITION_FORMATS), name="competition_format_valid"
        ),
        CheckConstraint("scope IN " + str(COMPETITION_SCOPES), name="competition_scope_valid"),
        # A domestic league has a tier; a cup and a continental competition do
        # not. Encoding it here stops "Cupa României, tier 3" existing at all.
        CheckConstraint(
            "(scope = 'DOMESTIC_LEAGUE') = (tier IS NOT NULL)",
            name="competition_tier_matches_scope",
        ),
        Index("ix_competition_country", "country_id", "tier"),
    )

    country_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("country.id", ondelete="RESTRICT")
    )
    # Stable and machine-readable: `liga-1`, `cupa-romaniei`, `uefa-conference`.
    key: Mapped[str] = mapped_column(String(48))
    name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str | None] = mapped_column(String(32))

    format: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(20))
    # Reference data is shared across every tenant, so a handball league and a
    # football league sit in the same table and are told apart by this.
    sport: Mapped[str] = mapped_column(
        String(24), default="FOOTBALL", server_default="FOOTBALL"
    )
    # 1 is the top flight. NULL for anything that is not a domestic league.
    tier: Mapped[int | None] = mapped_column(SmallInteger)

    # The competition's own badge, as a media asset if the platform holds one.
    badge_media_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class DirectoryClub(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """Every club that can appear in a fixture.

    Most opponents will never be customers, but a fixture list still needs
    their name and crest — that is half of what makes it look like a real
    football page. A tenant's own club links to its entry here, which is what
    makes two customers playing each other resolve to one match.
    """

    __tablename__ = "directory_club"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_directory_club_slug"),
        Index("ix_directory_club_country", "country_id", "name"),
    )

    country_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("country.id", ondelete="RESTRICT")
    )
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str] = mapped_column(String(16))
    city: Mapped[str | None] = mapped_column(String(120))
    founded_year: Mapped[int | None] = mapped_column(SmallInteger)
    venue_name: Mapped[str | None] = mapped_column(String(160))
    venue_capacity: Mapped[int | None] = mapped_column(Integer)
    # Public URL rather than a media id: most of these crests come from a
    # federation source, not from an upload by one of our clubs.
    crest_url: Mapped[str | None] = mapped_column(String(500))
    founded_year: Mapped[int | None] = mapped_column(SmallInteger)


class CompetitionSeason(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """One season of one competition.

    Liga 2 2025/26 is a different set of participants from Liga 2 2024/25, and a
    club promotes between them. Fixtures and tables belong to this, never to the
    competition itself.
    """

    __tablename__ = "competition_season"
    __table_args__ = (
        UniqueConstraint("competition_id", "name", name="uq_competition_season_name"),
        CheckConstraint("end_date > start_date", name="competition_season_dates_ordered"),
        Index("ix_competition_season_current", "competition_id", "is_current"),
    )

    competition_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("competition.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(default=False)

    # Points for a win. Three almost everywhere, but not everywhere and not
    # always historically — a table that hard-codes it is wrong the first time
    # it meets an exception.
    points_for_win: Mapped[int] = mapped_column(SmallInteger, default=3)
    points_for_draw: Mapped[int] = mapped_column(SmallInteger, default=1)


class CompetitionEntry(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A club taking part in a season of a competition."""

    __tablename__ = "competition_entry"
    __table_args__ = (
        UniqueConstraint(
            "competition_season_id", "directory_club_id", name="uq_competition_entry"
        ),
        Index("ix_competition_entry_club", "directory_club_id"),
    )

    competition_season_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("competition_season.id", ondelete="CASCADE")
    )
    directory_club_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("directory_club.id", ondelete="RESTRICT")
    )
    # Set for group formats; NULL for a straight league or knockout.
    group_label: Mapped[str | None] = mapped_column(String(8))
    # Carried into the season, e.g. a points deduction. Kept on the entry rather
    # than folded into the table, so the table stays a pure function of results.
    points_adjustment: Mapped[int] = mapped_column(SmallInteger, default=0)


class Match(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """One fixture, once.

    Global rather than tenant-scoped, for the reason in the module docstring: a
    match between two clubs is a single event that both of them — and every
    supporter of either — should see identically.
    """

    __tablename__ = "match"
    __table_args__ = (
        CheckConstraint("status IN " + str(MATCH_STATUSES), name="match_status_valid"),
        CheckConstraint("source IN " + str(MATCH_SOURCES), name="match_source_valid"),
        CheckConstraint("round_kind IN " + str(ROUND_KINDS), name="match_round_kind_valid"),
        CheckConstraint("home_club_id <> away_club_id", name="match_teams_differ"),
        # A score exists exactly when the match has been played. Anything else
        # is a fixture list that says 0-0 for next Saturday.
        # LIVE belongs here as much as FINISHED does: a match that has kicked
        # off has a score, and it is nil-nil until somebody scores. Leaving it
        # out would have meant a live scoreboard that could not store the one
        # number it exists to show.
        CheckConstraint(
            "(status IN ('FINISHED', 'AWARDED', 'LIVE')) = "
            "(home_score IS NOT NULL AND away_score IS NOT NULL)",
            name="match_score_matches_status",
        ),
        CheckConstraint(
            "home_score IS NULL OR home_score >= 0", name="match_home_score_non_negative"
        ),
        CheckConstraint(
            "away_score IS NULL OR away_score >= 0", name="match_away_score_non_negative"
        ),
        # The fixture-list query: one season, ordered by kick-off.
        Index("ix_match_season_kickoff", "competition_season_id", "kickoff_at"),
        # A club's own fixtures, from either side of the tie.
        Index("ix_match_home", "home_club_id", "kickoff_at"),
        Index("ix_match_away", "away_club_id", "kickoff_at"),
    )

    competition_season_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("competition_season.id", ondelete="CASCADE")
    )

    home_club_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("directory_club.id", ondelete="RESTRICT")
    )
    away_club_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("directory_club.id", ondelete="RESTRICT")
    )

    # A round is a kind, a number and a label — because "matchday 14",
    # "quarter-final" and "group stage, round 3" are three different things that
    # a single column cannot hold without lying about one of them.
    round_kind: Mapped[str] = mapped_column(String(12), default="MATCHDAY")
    round_number: Mapped[int | None] = mapped_column(SmallInteger)
    round_label: Mapped[str | None] = mapped_column(String(48))
    group_label: Mapped[str | None] = mapped_column(String(8))

    # Stored in UTC; the club's timezone turns it into a kick-off time. A
    # fixture without one is meaningless, and one without a zone is worse —
    # it is wrong twice a year.
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # True when only the date is known. The site then says "time to be
    # confirmed" instead of inventing 00:00.
    kickoff_is_confirmed: Mapped[bool] = mapped_column(default=True)

    venue_name: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(12), default="SCHEDULED")

    home_score: Mapped[int | None] = mapped_column(SmallInteger)
    away_score: Mapped[int | None] = mapped_column(SmallInteger)

    attendance: Mapped[int | None] = mapped_column(SmallInteger)
    # Where supporters buy for this match. External for now; when ticketing
    # lands, the target changes and the fixture list does not.
    ticket_url: Mapped[str | None] = mapped_column(String(500))

    source: Mapped[str] = mapped_column(String(16), default="CLUB")
    # Minute of play, while a provider says the match is on. Null otherwise —
    # a stale minute on a finished game reads as a live one.
    minute: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def is_played(self) -> bool:
        return self.status in ("FINISHED", "AWARDED")


class MatchEvent(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A goal, a card, a substitution — the story of a match.

    Global, like the match it belongs to: two clubs play one game, and each
    keeping its own copy of the goals would give the same match two scorers.

    Player names are stored as text rather than as a foreign key to `player`.
    The scorer is usually somebody else's player, who this platform has no row
    for and never will — and a goal that cannot be recorded because the scorer
    is not a customer would be an absurd rule.
    """

    __tablename__ = "match_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["match_id"], ["match.id"], name="fk_event_match", ondelete="CASCADE"
        ),
        CheckConstraint("kind IN " + str(EVENT_KINDS), name="event_kind_valid"),
        # One event per match, minute, kind and player. A re-sync must update
        # the goal it already knows about rather than add it a second time.
        UniqueConstraint(
            "match_id",
            "minute",
            "kind",
            "player_name",
            name="uq_match_event_moment",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_match_event_match", "match_id", "minute"),
    )

    match_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    # Which side. Null when the provider does not say, rather than guessed.
    club_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    minute: Mapped[int | None] = mapped_column(SmallInteger)
    extra_minute: Mapped[int | None] = mapped_column(SmallInteger)

    kind: Mapped[str] = mapped_column(String(16))
    # "Yellow Card", "Normal Goal", "Substitution 1" — the provider's own
    # wording, kept because it is the only thing distinguishing a penalty from
    # a header, and translated at the edge rather than lost here.
    detail: Mapped[str | None] = mapped_column(String(64))

    player_name: Mapped[str | None] = mapped_column(String(160))
    # The assist for a goal, or the player coming off in a substitution — the
    # provider uses one field for both, and so do we.
    related_name: Mapped[str | None] = mapped_column(String(160))
    comment: Mapped[str | None] = mapped_column(String(240))


class ClubSeasonRecord(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """Where a club finished, one season at a time.

    The club's history, and the only honest source of its palmarès: the
    provider has no endpoint for trophies won by a club, so a title is a first
    place in a league table rather than a claim somebody typed in.

    Stored rather than computed. A finished season's table is a fact that will
    not change, and recomputing it would mean holding every fixture the club
    ever played — for a club founded in 2009, tens of thousands of rows to
    answer "how did we do in 2021?".
    """

    __tablename__ = "club_season_record"
    __table_args__ = (
        UniqueConstraint(
            "directory_club_id",
            "competition_season_id",
            name="uq_club_season_record",
        ),
        Index("ix_club_season_record_club", "directory_club_id"),
    )

    directory_club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    competition_season_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    position: Mapped[int | None] = mapped_column(SmallInteger)
    played: Mapped[int] = mapped_column(SmallInteger, default=0)
    won: Mapped[int] = mapped_column(SmallInteger, default=0)
    drawn: Mapped[int] = mapped_column(SmallInteger, default=0)
    lost: Mapped[int] = mapped_column(SmallInteger, default=0)
    goals_for: Mapped[int] = mapped_column(SmallInteger, default=0)
    goals_against: Mapped[int] = mapped_column(SmallInteger, default=0)
    points: Mapped[int] = mapped_column(SmallInteger, default=0)
    # When the competition last recalculated this row. A published table is
    # stamped at midnight and does not absorb a matchday until hours later,
    # so this is what tells us which of our results it has already counted.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Recent results, newest first, as the provider gives them: "WWLDW".
    form: Mapped[str | None] = mapped_column(String(16))
    # What the provider called the outcome — "Promotion - Play-offs", say.
    # Kept because finishing third can mean promoted or nothing at all
    # depending on the division, and only the competition knows which.
    outcome: Mapped[str | None] = mapped_column(String(120))
