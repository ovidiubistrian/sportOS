"""Counting visitors without following them.

Two derived identifiers do all the work here, and both are designed to be
useless tomorrow.

**The visitor hash** is `sha256(salt-of-the-day + address + user agent + club)`.
It counts the same person twice in one day and cannot connect them to
yesterday, because the salt is random per day and never stored. There is no
cookie, so there is nothing to consent to and nothing to opt out of — which is
also why the numbers are not destroyed by a banner nobody clicks.

**The session** is minted server-side and kept in Redis for thirty minutes,
rolling. A visitor who reads four articles in ten minutes is one session; the
same person back in the evening is a second. Deriving it from a time window
instead would split anybody unlucky enough to read across the boundary.

Nothing personal is stored: not the address, not the agent string, not the
referring path — only its host, because a search URL carries what somebody
typed and the club does not need it.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

import structlog

from app.core.cache import cache
from app.core.ids import new_id

log = structlog.get_logger(__name__)

# Half an hour of silence ends a visit. The number is the web's convention and
# the one every other analytics product uses, which matters when a club
# compares this against whatever it had before.
SESSION_TTL_SECONDS = 30 * 60

# How long a visitor is the same visitor. One day, and then the salt changes
# and yesterday's hashes become unmatchable by construction.
_SALT_TTL_SECONDS = 60 * 60 * 36


async def _salt_for(day: date) -> str:
    """The day's secret, made once and shared by every worker.

    In Redis rather than in memory because two API replicas hashing the same
    visitor with different salts would count them twice. `SET NX` makes the
    first replica to ask the one that decides.
    """
    key = f"analytics:salt:{day.isoformat()}"
    existing = await cache.get_text(key)
    if existing:
        return existing

    minted = secrets.token_hex(16)
    await cache.set_text_if_absent(key, minted, _SALT_TTL_SECONDS)
    # Read back rather than trusting our own write: another replica may have
    # won the race, and both must agree.
    return (await cache.get_text(key)) or minted


async def visitor_hash(*, ip: str, user_agent: str, club_id: UUID) -> str:
    salt = await _salt_for(datetime.now(UTC).date())
    material = f"{salt}|{ip}|{user_agent}|{club_id}".encode()
    return hashlib.sha256(material).hexdigest()


async def session_for(visitor: str) -> str:
    """This visit's id, extended by every event in it."""
    key = f"analytics:sess:{visitor}"
    existing = await cache.get_text(key)
    if existing:
        # Rolling, not fixed: a long read should not end mid-article.
        await cache.expire(key, SESSION_TTL_SECONDS)
        return existing

    minted = str(new_id())
    await cache.set_text(key, minted, SESSION_TTL_SECONDS)
    return minted


def client_ip(forwarded_for: str | None, fallback: str | None) -> str:
    """The first address in the chain, which is the client's.

    Only ever hashed, never stored. If the proxy sends nothing we fall back to
    the socket address, and if that is missing too the hash is still stable for
    the day — it just groups the unknowns together.
    """
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return fallback or "unknown"


def referrer_host(referrer: str | None, own_host: str) -> str | None:
    """The host somebody came from, or nothing if they came from ourselves.

    Self-referrals are the majority of raw referrer data and none of them are
    a traffic source, so counting them would bury Facebook under the club's own
    home page.
    """
    if not referrer:
        return None
    try:
        host = (urlparse(referrer).hostname or "").lower()
    except ValueError:
        return None
    if not host or host == own_host.lower():
        return None
    return host[:160]


def device_of(user_agent: str) -> str:
    agent = user_agent.lower()
    if "ipad" in agent or "tablet" in agent:
        return "tablet"
    if "mobi" in agent or "android" in agent or "iphone" in agent:
        return "mobile"
    if agent:
        return "desktop"
    return "other"


def browser_of(user_agent: str) -> str:
    """Enough to answer "does the club need to test Safari", and no more.

    Deliberately coarse. A full user-agent parser is a dependency that needs
    updating forever, and the question a club asks is never finer than this.
    """
    agent = user_agent
    if "Edg/" in agent:
        return "Edge"
    if "OPR/" in agent or "Opera" in agent:
        return "Opera"
    if "Firefox/" in agent:
        return "Firefox"
    if "Chrome/" in agent or "CriOS" in agent:
        return "Chrome"
    if "Safari/" in agent:
        return "Safari"
    return "Other"


def is_bot(user_agent: str) -> bool:
    """Keep crawlers out of a club's numbers.

    Not a security control — a determined scraper lies — but a club looking at
    "5,000 visitors" should not be looking at Googlebot. Cheap string matching
    catches the honest majority, which is all that is being asked.
    """
    agent = user_agent.lower()
    if not agent:
        return True
    markers = (
        "bot",
        "crawler",
        "spider",
        "slurp",
        "curl",
        "wget",
        "python-requests",
        "httpx",
        "headless",
        "lighthouse",
        "pingdom",
        "uptime",
        "monitor",
        "preview",
        "facebookexternalhit",
        "whatsapp",
        "telegram",
    )
    return any(marker in agent for marker in markers)


def window(range_key: str) -> tuple[datetime, datetime, timedelta]:
    """The period being asked about, and the one before it to compare against.

    Returned as a span rather than a day count so "today" means since midnight
    rather than the last 24 hours — which is what somebody watching a matchday
    actually means by it.
    """
    now = datetime.now(UTC)
    if range_key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_key == "7d":
        start = now - timedelta(days=7)
    elif range_key == "90d":
        start = now - timedelta(days=90)
    else:
        start = now - timedelta(days=30)
    return start, now, now - start
