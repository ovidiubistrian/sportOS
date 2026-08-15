"""What a third party calls the things we already have.

One table rather than a `provider_id` column on each of `competition`,
`competition_season`, `directory_club` and `match`. Four columns would work
until the second provider arrives, and then it is eight — and every one of them
is a nullable column on a table that does not otherwise care that integrations
exist.

The link is deliberately not a foreign key. `local_id` points at whichever table
`entity_type` names, which is the same polymorphic trade the ordering kernel
makes: no database-level integrity, in exchange for one table that does not have
to be altered to support a new kind of thing.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Base,
    GlobalModel,
    TenantScoped,
    Timestamped,
    UUIDPrimaryKey,
)

PROVIDERS = ("API_FOOTBALL",)

LINKED_ENTITIES = (
    "COMPETITION",
    "COMPETITION_SEASON",
    "DIRECTORY_CLUB",
    "MATCH",
)

FEED_MODES = ("MANUAL", "FEED")


class ProviderLink(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A row of ours, and the id a provider knows it by.

    Global, like everything it points at: competitions, the club directory and
    fixtures are platform reference data shared across tenants. A provider id
    for one tenant's private data would belong on that tenant's own row, not
    here.
    """

    __tablename__ = "provider_link"
    __table_args__ = (
        # One provider id per local row, and one local row per provider id —
        # both directions, because a duplicate either way silently doubles
        # every fixture the next sync writes.
        UniqueConstraint("provider", "entity_type", "local_id", name="uq_provider_link_local"),
        UniqueConstraint(
            "provider", "entity_type", "provider_id", name="uq_provider_link_remote"
        ),
        Index("ix_provider_link_lookup", "provider", "entity_type", "provider_id"),
    )

    provider: Mapped[str] = mapped_column(String(24))
    entity_type: Mapped[str] = mapped_column(String(24))
    local_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    provider_id: Mapped[str] = mapped_column(String(64))

    # What the provider last told us about this thing. Kept so a mapping
    # problem can be diagnosed without spending another API call, and so a
    # field we do not read yet is not lost.
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncRun(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """One attempt at pulling something, and what it cost.

    The platform pays per call on a shared allowance, so "who spent the quota"
    has to be answerable. Rows are per run, not per call: a fixtures pull for
    one season is one run whatever it takes.
    """

    __tablename__ = "provider_sync_run"
    __table_args__ = (Index("ix_sync_run_recent", "provider", "started_at"),)

    provider: Mapped[str] = mapped_column(String(24))
    # FIXTURES | STANDINGS | TEAMS | SQUAD | LIVE
    kind: Mapped[str] = mapped_column(String(24))
    # The tenant whose linked competition caused it, when there is one. Null
    # for a platform-wide pull such as the competition catalogue.
    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    competition_season_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")

    requests: Mapped[int] = mapped_column(default=0)
    created: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(500))


class ClubFeed(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Whether a club's calendar comes from the provider, and how often.

    Per club rather than per platform, because the answer genuinely differs:
    a Liga II side has full coverage, a Liga III side has fixtures but often no
    live events, and a Liga IV side is not in the provider's catalogue at all.
    `MANUAL` is a real choice rather than the absence of one — a club that will
    never be covered should see that stated, not a switch that quietly does
    nothing.

    Synced by *team*, not by league. One call to `fixtures?team=X&season=Y`
    returns everything they play — league, cup and all — where syncing by
    league would need one call per competition and still miss the cup.
    """

    __tablename__ = "club_feed"
    __table_args__ = (
        UniqueConstraint("tenant_id", "club_id", "provider", name="uq_club_feed_club"),
        CheckConstraint("mode IN " + str(FEED_MODES), name="club_feed_mode_valid"),
        CheckConstraint(
            "live_interval_minutes BETWEEN 1 AND 1440",
            name="club_feed_live_interval_sane",
        ),
        Index("ix_club_feed_due", "provider", "mode"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(24), default="API_FOOTBALL")
    mode: Mapped[str] = mapped_column(String(16), default="MANUAL")

    # The provider's id for this club's team. Null while the club has not been
    # matched to one, which is also what MANUAL means in practice.
    provider_team_id: Mapped[str | None] = mapped_column(String(32))
    provider_team_name: Mapped[str | None] = mapped_column(String(160))
    # Which season year to ask for. Not derived from the calendar: the provider
    # has Liga I on 2026 and Liga III on 2025 at the same moment.
    season_year: Mapped[int | None] = mapped_column(SmallInteger)

    sync_fixtures: Mapped[bool] = mapped_column(default=True)
    sync_standings: Mapped[bool] = mapped_column(default=True)
    sync_live: Mapped[bool] = mapped_column(default=False)

    # The club's own pacing, bounded by the platform's quota. Ten minutes is
    # the default because it is frequent enough to feel live and cheap enough
    # that a full matchday costs a dozen calls.
    live_interval_minutes: Mapped[int] = mapped_column(SmallInteger, default=10)
    fixtures_interval_hours: Mapped[int] = mapped_column(SmallInteger, default=12)

    last_fixtures_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_standings_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_live_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
