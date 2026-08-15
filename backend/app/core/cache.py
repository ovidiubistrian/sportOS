"""Redis access.

Redis is a cache and a coordination primitive. It is never a source of truth:
anything lost here must be recoverable from PostgreSQL. See
docs/architecture/03-data-model.md §12.1 for why that matters most in ticketing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)


class Cache:
    """One client per event loop.

    The application runs a single loop, so this resolves to a single pooled
    client in production. It is keyed by loop because a redis connection pool
    holds futures bound to the loop that created it: reuse it from another loop
    and the call fails with "attached to a different loop". The test suite runs
    each test on a fresh loop, and the failure mode there was ugly — a cache
    invalidation raising *after* the database write it was meant to accompany,
    leaving the cache holding an answer the database no longer agrees with.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._clients: dict[int, aioredis.Redis] = {}

    @property
    def client(self) -> aioredis.Redis:
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:  # no loop yet; the first await will re-resolve
            loop_id = 0
        client = self._clients.get(loop_id)
        if client is None:
            client = aioredis.from_url(self._url, encoding="utf-8", decode_responses=True)
            self._clients[loop_id] = client
        return client

    async def get_json(self, key: str) -> Any | None:
        raw = await self.client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # A malformed entry is a cache miss, never an error surfaced to a user.
            log.warning("cache_decode_failed", key=key)
            return None

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        await self.client.set(key, json.dumps(value, default=str), ex=ttl)

    async def get_int(self, key: str, default: int = 0) -> int:
        raw = await self.client.get(key)
        try:
            return int(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    async def get_text(self, key: str) -> str | None:
        value = await self.client.get(key)
        return str(value) if value is not None else None

    async def set_text(self, key: str, value: str, ttl: int) -> None:
        await self.client.set(key, value, ex=ttl)

    async def set_text_if_absent(self, key: str, value: str, ttl: int) -> bool:
        """Write only if nobody has. Returns whether this caller won.

        Used where several replicas must agree on one generated value — the
        analytics salt of the day — and the alternative is each of them minting
        its own and counting the same visitor several times.
        """
        return bool(await self.client.set(key, value, ex=ttl, nx=True))

    async def incr(self, key: str) -> int:
        return int(await self.client.incr(key))

    async def expire(self, key: str, seconds: int) -> None:
        """Set a lifetime on a counter.

        Separate from `incr` so a rate-limit window is set once, on the
        first attempt, rather than reset on every subsequent one — which
        would let a caller hold a window open forever by keeping up the
        pressure.
        """
        await self.client.expire(key, seconds)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self.client.delete(*keys)

    async def clear_prefix(self, prefix: str) -> int:
        """Drop every key under a prefix.

        SCAN, not KEYS: this runs on a live Redis during a deploy, and KEYS on a
        large keyspace blocks the server for everyone. Returns how many went, so
        the caller can log something more useful than "done".
        """
        removed = 0
        async for key in self.client.scan_iter(match=f"{prefix}*", count=500):
            await self.client.delete(key)
            removed += 1
        return removed

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception as exc:  # pragma: no cover - health path
            log.error("redis_healthcheck_failed", error=str(exc))
            return False

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


cache = Cache(settings.redis_url)
