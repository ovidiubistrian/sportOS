"""The API-Football HTTP client.

One platform-held key serves every club, which makes the daily allowance a
shared resource rather than each tenant's own problem. Three consequences shape
this file:

* every call is counted, so "which club spent the quota" is answerable;
* the provider's own remaining-quota headers are read and respected, because
  finding out by being rejected wastes a call to learn it;
* nothing here is called while rendering a page. Sync is scheduled, and a club
  site stays up when the provider is down, slow or unpaid.

The provider answers 200 with an `errors` object for things other APIs would
give a 4xx, so success is checked in the body, not only in the status line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

PROVIDER = "API_FOOTBALL"


class ProviderUnavailable(RuntimeError):
    """The provider cannot answer right now. Never surfaced to a supporter."""


class ProviderNotConfigured(ProviderUnavailable):
    """No key. Distinguished so the console can say so plainly."""


class QuotaExhausted(ProviderUnavailable):
    """The shared daily allowance is spent."""


@dataclass(slots=True)
class Usage:
    """What a sync cost, and what is left on the shared key."""

    requests: int = 0
    remaining: int | None = None
    limit: int | None = None


@dataclass(slots=True)
class ApiFootball:
    """A client scoped to one sync run, so its cost is attributable."""

    usage: Usage = field(default_factory=Usage)
    _client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(settings.api_football_key.get_secret_value())

    async def __aenter__(self) -> ApiFootball:
        if not self.is_configured:
            raise ProviderNotConfigured("No API-Football key is configured on this platform.")
        self._client = httpx.AsyncClient(
            base_url=settings.api_football_base_url,
            timeout=settings.api_football_timeout_seconds,
            headers={"x-apisports-key": settings.api_football_key.get_secret_value()},
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, path: str, **params: Any) -> list[dict[str, Any]]:
        """One call, counted, with the provider's errors treated as errors."""
        if self._client is None:  # pragma: no cover - misuse
            raise RuntimeError("Use ApiFootball as an async context manager.")

        # Checked before spending rather than after: the whole point of reading
        # the headers is not to learn the limit by hitting it.
        if self.usage.remaining is not None and self.usage.remaining <= 0:
            raise QuotaExhausted("The daily API-Football allowance is spent.")

        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"API-Football did not answer: {exc}") from exc

        self.usage.requests += 1
        self._read_quota(response.headers)

        if response.status_code == 429:
            raise QuotaExhausted("API-Football is rate limiting this key.")
        if response.status_code >= 500:
            raise ProviderUnavailable(f"API-Football returned {response.status_code}.")
        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"API-Football rejected the request ({response.status_code})."
            )

        body = response.json()

        # A 200 with an `errors` object is this provider's idea of a 4xx. An
        # empty *list* means no errors; a dict means something is wrong.
        errors = body.get("errors")
        if isinstance(errors, dict) and errors:
            detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
            if "limit" in detail.lower() or "plan" in detail.lower():
                raise QuotaExhausted(detail)
            raise ProviderUnavailable(detail)

        return list(body.get("response") or [])

    def _read_quota(self, headers: httpx.Headers) -> None:
        for name, target in (
            ("x-ratelimit-requests-remaining", "remaining"),
            ("x-ratelimit-requests-limit", "limit"),
        ):
            raw = headers.get(name)
            if raw is None:
                continue
            try:
                setattr(self.usage, target, int(raw))
            except ValueError:
                continue

    # --- the endpoints this platform actually uses ------------------------

    async def leagues(self, *, country: str | None = None) -> list[dict[str, Any]]:
        return await self.get("/leagues", **({"country": country} if country else {}))

    async def teams(self, *, league: str, season: int) -> list[dict[str, Any]]:
        return await self.get("/teams", league=league, season=season)

    async def fixtures(
        self, *, league: str, season: int, team: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"league": league, "season": season}
        if team:
            params["team"] = team
        return await self.get("/fixtures", **params)

    async def fixtures_for_team(self, *, team: str, season: int) -> list[dict[str, Any]]:
        """Every fixture one club plays that season, across all competitions.

        One call for the league, the cup and Europe together — which is both
        cheaper and more complete than asking league by league, since a club
        can be drawn into a cup we have no mapping for yet.
        """
        return await self.get("/fixtures", team=team, season=season)

    async def search_teams(self, *, query: str) -> list[dict[str, Any]]:
        """Find a club by name, so an admin can pick theirs from a list."""
        return await self.get("/teams", search=query)

    async def live_fixtures(self, *, ids: list[str]) -> list[dict[str, Any]]:
        """Only the matches that are actually on — never a blanket live poll.

        `all` would return every game in the world on a Saturday afternoon and
        spend the allowance on clubs nobody here supports.
        """
        if not ids:
            return []
        return await self.get("/fixtures", ids="-".join(ids[:20]))

    async def standings(self, *, league: str, season: int) -> list[dict[str, Any]]:
        return await self.get("/standings", league=league, season=season)

    async def coaches(self, *, team: str) -> list[dict[str, Any]]:
        """Whoever the provider has managing this club.

        Only the head coach. There is no assistant, no goalkeeping coach and no
        physio in this catalogue — a club's technical staff below the manager
        is not something a results provider tracks.
        """
        return await self.get("/coachs", team=team)

    async def squad(self, *, team: str) -> list[dict[str, Any]]:
        return await self.get("/players/squads", team=team)
