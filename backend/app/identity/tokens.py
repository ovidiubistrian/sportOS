"""OIDC access-token verification.

Signature, issuer, audience, expiry and authorised party are all checked. The
token establishes *who* the caller is and nothing else — no scopes, no
permissions, no tenant authority. Those come from our database on every
request. See ADR-0003.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
import structlog
from jwt import PyJWKSet

from app.core.config import settings
from app.core.errors import Unauthenticated

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject_id: str
    email: str
    email_verified: bool
    given_name: str | None
    family_name: str | None
    authorised_party: str | None
    auth_time: datetime | None
    amr: frozenset[str]
    # Keycloak's answer to "how hard did they prove it". A level, not a list of
    # methods — see `Principal.has_second_factor` for why both are read.
    acr: str | None
    raw: dict[str, Any]


class JwksCache:
    """Caches the realm's signing keys, refreshing on an unknown `kid`.

    Refreshing on unknown key id rather than only on TTL means a key rotation
    is picked up within one request instead of within the TTL window.
    """

    def __init__(self) -> None:
        self._keys: PyJWKSet | None = None
        self._fetched_at: float = 0.0
        self._jwks_uri: str | None = None

    async def _discover(self, client: httpx.AsyncClient) -> str:
        if self._jwks_uri:
            return self._jwks_uri
        url = f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        response = await client.get(url, timeout=5.0)
        response.raise_for_status()
        self._jwks_uri = str(response.json()["jwks_uri"])
        return self._jwks_uri

    async def _refresh(self) -> None:
        async with httpx.AsyncClient() as client:
            jwks_uri = await self._discover(client)
            response = await client.get(jwks_uri, timeout=5.0)
            response.raise_for_status()
            self._keys = PyJWKSet.from_dict(response.json())
            self._fetched_at = time.monotonic()

    async def key_for(self, kid: str) -> Any:
        expired = (
            self._keys is None
            or time.monotonic() - self._fetched_at > settings.oidc_jwks_cache_seconds
        )
        if expired:
            await self._refresh()
        try:
            return self._get(kid)
        except KeyError:
            await self._refresh()
            try:
                return self._get(kid)
            except KeyError as exc:
                raise Unauthenticated("Token signing key is not recognised.") from exc

    def _get(self, kid: str) -> Any:
        assert self._keys is not None
        for key in self._keys.keys:
            if key.key_id == kid:
                return key.key
        raise KeyError(kid)


jwks_cache = JwksCache()


async def verify_access_token(token: str) -> TokenClaims:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise Unauthenticated("Malformed token.") from exc

    kid = header.get("kid")
    if not kid:
        raise Unauthenticated("Token has no key id.")

    key = await jwks_cache.key_for(kid)

    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            options={"require": ["exp", "iat", "sub", "iss"]},
            leeway=10,
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthenticated("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        log.info("token_rejected", reason=str(exc))
        raise Unauthenticated("Token is not valid.") from exc

    if claims.get("iss") not in settings.accepted_issuers:
        raise Unauthenticated("Token issuer is not recognised.")

    azp = claims.get("azp")
    if azp and azp not in settings.oidc_allowed_clients:
        raise Unauthenticated("Token was issued to an unknown client.")

    email = claims.get("email")
    if not email:
        raise Unauthenticated("Token does not identify an email address.")

    auth_time_raw = claims.get("auth_time")
    return TokenClaims(
        subject_id=str(claims["sub"]),
        email=str(email),
        email_verified=bool(claims.get("email_verified", False)),
        given_name=claims.get("given_name"),
        family_name=claims.get("family_name"),
        authorised_party=azp,
        auth_time=(
            datetime.fromtimestamp(int(auth_time_raw), tz=UTC) if auth_time_raw else None
        ),
        amr=frozenset(claims.get("amr", []) or []),
        acr=(str(claims["acr"]) if claims.get("acr") is not None else None),
        raw=claims,
    )
