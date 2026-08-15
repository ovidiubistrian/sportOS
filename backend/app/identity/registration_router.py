"""Sign-up routes.

Unauthenticated by definition — there is nobody to authenticate yet — which
makes this the most exposed surface in the product. Two things follow from
that: it is rate limited on two independent keys, and it runs on the platform
session with no tenant bound, because there is no tenant until it succeeds.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.cache import cache
from app.core.db import platform_session
from app.core.errors import RateLimited
from app.core.locales import LOCALE_CODES, SUPPORTED_LOCALES
from app.identity.registration import (
    MIN_PASSWORD_LENGTH,
    SignUp,
    register,
    slug_available,
    slugify,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/public/register", tags=["public"])

# Two windows, because they stop different things. The per-address limit stops
# someone hammering one club's name; the per-caller limit stops a script
# creating a hundred tenants. Neither alone is enough.
ATTEMPTS_PER_IP = 5
ATTEMPTS_PER_IP_WINDOW = 3600
ATTEMPTS_PER_EMAIL = 3
ATTEMPTS_PER_EMAIL_WINDOW = 3600


class SignUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    club_name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=3, max_length=48)
    country_code: str = Field(min_length=2, max_length=2)
    locale: str = Field(min_length=2, max_length=10)

    @field_validator("locale")
    @classmethod
    def _known_locale(cls, value: str) -> str:
        base = value.strip().lower().split("-")[0]
        if base not in LOCALE_CODES:
            raise ValueError(f"must be one of {', '.join(sorted(LOCALE_CODES))}")
        return base

    @field_validator("slug")
    @classmethod
    def _normalise_slug(cls, value: str) -> str:
        return value.strip().lower()


class SignUpResponse(BaseModel):
    club_slug: str
    email: str
    # The interface uses this to say "check your email" rather than dropping
    # someone into an app they cannot use yet.
    verification_required: bool = True


class SlugCheck(BaseModel):
    slug: str
    available: bool
    suggestion: str | None = None


class LocaleOut(BaseModel):
    code: str
    endonym: str
    english_name: str


def _caller(request: Request) -> str:
    # Behind the proxy, so the first hop in X-Forwarded-For is the real client.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _rate_limit(key: str, limit: int, window: int) -> None:
    used = await cache.incr(f"signup:{key}")
    if used == 1:
        await cache.expire(f"signup:{key}", window)
    if used > limit:
        log.warning("signup_rate_limited", key=key)
        raise RateLimited("Too many attempts. Please wait a little and try again.")


@router.get("/languages", response_model=list[LocaleOut], summary="Languages on offer")
async def languages() -> list[LocaleOut]:
    """What a club may choose at sign-up.

    Served from the same registry the rest of the platform validates against,
    so the form can never offer a language the API would refuse.
    """
    return [
        LocaleOut(
            code=locale.code,
            endonym=locale.endonym,
            english_name=locale.english_name,
        )
        for locale in SUPPORTED_LOCALES
    ]


@router.get("/slug", response_model=SlugCheck, summary="Is this address free?")
async def check_slug(request: Request, name: str = "") -> SlugCheck:
    """Live feedback while someone types their club's name.

    Rate limited too: without it this is a free enumeration of every club on the
    platform.
    """
    await _rate_limit(f"slug:{_caller(request)}", 60, 300)

    slug = slugify(name)
    if len(slug) < 3:
        return SlugCheck(slug=slug, available=False)

    async with platform_session(reason="check a sign-up address", routine=True) as session:
        if await slug_available(session, slug):
            return SlugCheck(slug=slug, available=True)

        # Suggest something rather than only refusing. A club whose obvious
        # name is taken should not have to invent one unaided.
        for suffix in ("-fc", "-club", "-official", "-2", "-3"):
            candidate = f"{slug}{suffix}"[:48]
            if await slug_available(session, candidate):
                return SlugCheck(slug=slug, available=False, suggestion=candidate)
        return SlugCheck(slug=slug, available=False)


@router.post(
    "",
    response_model=SignUpResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and a club",
    responses={
        409: {"description": "The address or the email is already taken"},
        429: {"description": "Too many attempts"},
        503: {"description": "The identity provider is unavailable"},
    },
)
async def sign_up(payload: SignUpRequest, request: Request) -> SignUpResponse:
    await _rate_limit(_caller(request), ATTEMPTS_PER_IP, ATTEMPTS_PER_IP_WINDOW)
    await _rate_limit(
        f"email:{payload.email.lower()}", ATTEMPTS_PER_EMAIL, ATTEMPTS_PER_EMAIL_WINDOW
    )

    # No tenant is bound because none exists yet. This is the one write path in
    # the product that legitimately runs before tenant context — which is why it
    # creates exactly one tenant and nothing else can reach it.
    async with platform_session(reason="register a new tenant") as session:
        result = await register(
            session,
            SignUp(
                email=str(payload.email).lower(),
                password=payload.password,
                first_name=payload.first_name.strip(),
                last_name=payload.last_name.strip(),
                club_name=payload.club_name.strip(),
                slug=payload.slug,
                country_code=payload.country_code,
                locale=payload.locale,
            ),
        )

    return SignUpResponse(club_slug=result.club_slug, email=result.email)
