"""What differs between one team sport and the next.

Almost nothing in this product is about football. A club, a season, a squad, a
registration, a fixture, a result, a table, a shop, a supporter — a handball
club has every one of them and means the same thing by each. What football
actually owns is a short list: how many points a win is worth, whether a draw
can happen at all, whether the thing you score is called a goal, which events
are worth recording, and what the positions are called.

So that list lives here, as data, and the rest of the application asks.

Two design notes worth keeping.

**The profile is not a feature flag.** It is answered per *team*, because a
Romanian CSM is routinely one legal entity running football, handball and
volleyball — one tenant, three sports, and a fixture belongs to whichever team
plays it. Resolution falls back team → club → tenant so a single-sport club
never has to say it three times.

**FOOTBALL reproduces exactly what was hardcoded.** Every existing row defaults
to it, so introducing this changed no behaviour anywhere; the suite that passed
before was the proof. Adding a sport is a new entry in this file plus its
labels in the catalogue — not a new screen, and not a branch in a component.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SportProfile:
    key: str
    name: str

    # --- how a result is decided ------------------------------------------
    #
    # `points_for_draw` is 0 where draws cannot happen, which is not a fudge:
    # basketball plays overtime until somebody wins, so a drawn *result* never
    # reaches the table.
    points_for_win: int = 3
    points_for_draw: int = 1
    points_for_loss: int = 0
    draws_possible: bool = True

    # What one unit of score is called. Drives every label from the scoreboard
    # to the league table's "GF/GA" columns, so handball does not say "goals
    # for" and basketball does not say "goals" at all.
    scoring_unit: str = "GOAL"

    # --- how a match is shaped --------------------------------------------
    period_count: int = 2
    period_minutes: int | None = 45
    # Volleyball is played to a score rather than a clock, so "73'" is not a
    # thing that can be said about it and no minute is asked for or shown.
    tracks_minute: bool = True

    # --- what can happen in one -------------------------------------------
    event_kinds: tuple[str, ...] = ("GOAL", "CARD", "SUBSTITUTION", "VAR")
    positions: tuple[str, ...] = ()

    # Which external feed, if any, can supply fixtures and results. Only
    # football has one today; the rest are entered by hand, which is the same
    # thing Liga 4 and 5 football clubs already do.
    provider: str | None = None

    @property
    def counts_sets(self) -> bool:
        """Is the score a count of periods won rather than of points scored?"""
        return self.period_minutes is None


FOOTBALL = SportProfile(
    key="FOOTBALL",
    name="Football",
    positions=("GK", "RB", "CB", "LB", "DM", "CM", "AM", "RW", "LW", "ST"),
    provider="API_FOOTBALL",
)

FUTSAL = SportProfile(
    key="FUTSAL",
    name="Futsal",
    period_minutes=20,
    positions=("GK", "DEF", "WING", "PIVOT", "UNIVERSAL"),
)

HANDBALL = SportProfile(
    key="HANDBALL",
    name="Handball",
    # Two for a win, one each for a draw — the European league standard.
    points_for_win=2,
    period_minutes=30,
    positions=("GK", "LW", "LB", "CB", "RB", "RW", "PIVOT"),
    # A handball suspension is a two-minute exclusion, not a substitution.
    event_kinds=("GOAL", "CARD", "SUSPENSION", "SUBSTITUTION"),
)

BASKETBALL = SportProfile(
    key="BASKETBALL",
    name="Basketball",
    # Overtime is played until somebody wins, so a draw never reaches a table.
    points_for_win=2,
    points_for_draw=0,
    draws_possible=False,
    scoring_unit="POINT",
    period_count=4,
    period_minutes=10,
    positions=("PG", "SG", "SF", "PF", "C"),
    event_kinds=("SCORE", "FOUL", "SUBSTITUTION"),
)

VOLLEYBALL = SportProfile(
    key="VOLLEYBALL",
    name="Volleyball",
    # Three points for a 3-0 or 3-1, two for a 3-2 — the split is a property of
    # the competition, so the season's own points fields carry it. What belongs
    # here is that a draw is impossible.
    points_for_win=3,
    points_for_draw=0,
    draws_possible=False,
    scoring_unit="SET",
    period_count=5,
    period_minutes=None,
    tracks_minute=False,
    positions=("OH", "OPP", "MB", "S", "L"),
    event_kinds=("SET",),
)

RUGBY = SportProfile(
    key="RUGBY",
    name="Rugby union",
    points_for_win=4,
    points_for_draw=2,
    scoring_unit="POINT",
    period_minutes=40,
    positions=("PR", "HK", "LK", "FL", "N8", "SH", "FH", "CE", "WG", "FB"),
    event_kinds=("TRY", "CONVERSION", "PENALTY", "CARD", "SUBSTITUTION"),
)

ICE_HOCKEY = SportProfile(
    key="ICE_HOCKEY",
    name="Ice hockey",
    period_count=3,
    period_minutes=20,
    positions=("G", "D", "LW", "C", "RW"),
    event_kinds=("GOAL", "PENALTY", "SUBSTITUTION"),
)

WATER_POLO = SportProfile(
    key="WATER_POLO",
    name="Water polo",
    period_count=4,
    period_minutes=8,
    positions=("GK", "CF", "CB", "D", "W"),
    event_kinds=("GOAL", "EXCLUSION", "SUBSTITUTION"),
)

SPORTS: tuple[SportProfile, ...] = (
    FOOTBALL,
    FUTSAL,
    HANDBALL,
    BASKETBALL,
    VOLLEYBALL,
    RUGBY,
    ICE_HOCKEY,
    WATER_POLO,
)

BY_KEY: dict[str, SportProfile] = {sport.key: sport for sport in SPORTS}

SPORT_KEYS: tuple[str, ...] = tuple(BY_KEY)

DEFAULT_SPORT = FOOTBALL.key


def profile(key: str | None) -> SportProfile:
    """The rules for a sport, falling back to football.

    A fallback rather than an error on purpose: an unknown value means a sport
    was removed while rows still pointed at it, and a club's website going down
    is a worse answer to that than showing football's rules until somebody
    fixes the data.
    """
    return BY_KEY.get(key or "", FOOTBALL)


def positions_for(key: str | None) -> tuple[str, ...]:
    return profile(key).positions


def event_kinds_for(key: str | None) -> tuple[str, ...]:
    return profile(key).event_kinds


# Every event kind any sport can produce. The database constraint has to admit
# all of them; which are *meaningful* is the profile's business, checked in the
# service where the sport of the match is known.
ALL_EVENT_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(kind for sport in SPORTS for kind in sport.event_kinds)
)

# Likewise for positions: one column, every sport's vocabulary.
ALL_POSITIONS: tuple[str, ...] = tuple(
    dict.fromkeys(position for sport in SPORTS for position in sport.positions)
)


@dataclass(frozen=True, slots=True)
class SportSummary:
    """What the outside world needs to know about a sport."""

    key: str
    name: str
    scoring_unit: str
    draws_possible: bool
    tracks_minute: bool
    positions: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, sport: SportProfile) -> SportSummary:
        return cls(
            key=sport.key,
            name=sport.name,
            scoring_unit=sport.scoring_unit,
            draws_possible=sport.draws_possible,
            tracks_minute=sport.tracks_minute,
            positions=sport.positions,
        )
