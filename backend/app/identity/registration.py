"""Sign-up.

Four things have to come into existence together — a login, a tenant, its first
club, and the owner's role — and they live in two systems that cannot share a
transaction. So the order is chosen so that the only possible orphan is the
harmless one:

    1. check the address is free
    2. create the login in Keycloak
    3. create the tenant, club, person and owner role in one PostgreSQL
       transaction
    4. if step 3 fails, delete the login again

A failure at step 3 that we successfully compensate leaves nothing behind. A
failure at step 3 whose compensation *also* fails leaves a login with no tenant:
the person signs in and is told they have no club access. Recoverable, visible,
and cleanable by a sweep.

The opposite order would leave a *tenant with no owner* — a club that exists,
holds a slug, and that nobody can ever sign into. That one needs a human to fix,
which is why it is the outcome this ordering designs out.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.models import Role, RoleAssignment
from app.core.config import settings
from app.core.countries import currency_for
from app.core.errors import Conflict, ValidationFailed
from app.core.ids import new_id
from app.core.locales import normalise, validate
from app.identity.keycloak import get_admin
from app.identity.models import Person, UserAccount
from app.tenants.branding_models import ClubBranding
from app.tenants.domain_service import attach, hostname_for
from app.tenants.models import Club, Tenant
from app.tenants.slugs import is_reserved

# What a new club is put on while it decides. CLUB rather than STARTER: the
# point of a trial is to show what the product does, and a trial that hides the
# shop and the ticketing behind an upgrade prompt shows the opposite.
TRIAL_PLAN = "CLUB"
TRIAL_LENGTH = timedelta(days=30)

log = structlog.get_logger(__name__)

MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True, slots=True)
class SignUp:
    email: str
    password: str
    first_name: str
    last_name: str
    club_name: str
    slug: str
    country_code: str
    locale: str


@dataclass(frozen=True, slots=True)
class Registered:
    tenant_id: str
    club_id: str
    club_slug: str
    email: str


def slugify(value: str) -> str:
    """A club name to a URL segment.

    Diacritics are folded rather than dropped, so "Știința" becomes `stiinta`
    and not `tiina` — a Romanian club should recognise its own address.
    """
    folded = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)[:48]


async def _start_trial(session, tenant_id: UUID, now: datetime) -> None:
    """Put a new tenant on a trial of the standard plan.

    Without this a tenant has no subscription at all, and entitlements fall back
    to the handful of features that default open — so a club that has just
    signed up finds the shop, ticketing and memberships all answering 402 with
    nothing on screen explaining why. A trial is also the honest offer: they
    have not paid, and at the end of it somebody has to choose a plan.
    """
    from app.billing.models import Plan, PlanVersion, TenantSubscription

    # The newest version of the plan: versions are append-only, so "current"
    # is the highest one rather than a flag somebody has to remember to move.
    version = await session.scalar(
        select(PlanVersion)
        .join(Plan, Plan.id == PlanVersion.plan_id)
        .where(Plan.key == TRIAL_PLAN)
        .order_by(PlanVersion.version.desc())
        .limit(1)
    )
    if version is None:
        # Reference data missing means a broken deployment, but refusing the
        # sign-up over it would be worse: the club is registered, and an
        # operator can attach a plan afterwards.
        log.warning("trial_plan_missing", plan=TRIAL_PLAN, tenant_id=str(tenant_id))
        return

    session.add(
        TenantSubscription(
            id=new_id(),
            tenant_id=tenant_id,
            plan_version_id=version.id,
            status="TRIALING",
            currency="EUR",
            current_period_start=now,
            trial_ends_at=now + TRIAL_LENGTH,
        )
    )
    await session.flush()


def short_name_for(club_name: str) -> str:
    """A crest-sized abbreviation, at most eight characters.

    Initials when the name has several words, because that is what a club puts
    on a badge — "Fotbal Club Argeș" reads as FCA, not as "Fotbal C". Falls back
    to a truncation for single-word names.
    """
    words = [w for w in re.split(r"[\s.-]+", club_name.strip()) if w]
    if len(words) >= 2:
        initials = "".join(word[0] for word in words if word[0].isalnum()).upper()
        if 2 <= len(initials) <= 8:
            return initials
    return club_name.strip()[:8].upper()


def validate_slug(slug: str) -> str:
    if len(slug) < 3:
        raise ValidationFailed(
            "That address is too short. Use at least three characters.", field="slug"
        )
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", slug):
        raise ValidationFailed(
            "An address may contain lowercase letters, numbers and hyphens.",
            field="slug",
        )
    if is_reserved(slug):
        # A slug is a path on the platform host. One that collides with a
        # platform page would shadow it — and slugs are permanent in practice,
        # so this has to be refused now rather than migrated later.
        raise ValidationFailed("That address is reserved. Please choose another.", field="slug")
    return slug


def validate_password(password: str) -> str:
    """Length, and nothing else.

    No character-class rules: they push people towards `Password1!` and are
    weaker than a long passphrase. Length is the property that actually costs
    an attacker something.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(
            f"Use at least {MIN_PASSWORD_LENGTH} characters. A short sentence works well.",
            field="password",
        )
    return password


async def slug_available(session: AsyncSession, slug: str) -> bool:
    if is_reserved(slug):
        return False
    taken = await session.scalar(select(Club.id).where(Club.slug == slug))
    return taken is None


async def _create_records(session: AsyncSession, signup: SignUp, subject_id: str) -> Registered:
    """Everything that lives in PostgreSQL, in one transaction."""
    slug = signup.slug
    locale = normalise(signup.locale)
    supported = validate([locale])
    # The country already answers this; asking a Romanian club to confirm it
    # uses lei is a question with one right answer. Changeable in settings.
    currency = currency_for(signup.country_code)

    now = datetime.now(UTC)
    tenant = Tenant(
        id=new_id(),
        slug=slug,
        legal_name=signup.club_name,
        trading_name=signup.club_name,
        country_code=signup.country_code.upper(),
        default_locale=locale,
        supported_locales=supported,
        default_currency=currency,
        timezone="UTC",
        # Not ACTIVE. The address is claimed but the account is unproven until
        # the verification email is answered — otherwise anyone could take a
        # club's name with an address they do not control.
        #
        # ACTIVE immediately where verification is switched off, because a
        # tenant left PENDING by a mail that will never arrive is a club that
        # can sign in and then find nothing works.
        status="PENDING" if settings.require_email_verification else "ACTIVE",
    )
    session.add(tenant)
    # Flushed before anything references it. These models carry foreign key
    # columns but no ORM relationships, so SQLAlchemy's unit of work has no way
    # to infer that the tenant must be inserted first — it has to be told.
    await session.flush()

    club = Club(
        id=new_id(),
        tenant_id=tenant.id,
        slug=slug,
        legal_name=signup.club_name,
        display_name=signup.club_name,
        short_name=short_name_for(signup.club_name),
        country_code=signup.country_code.upper(),
        default_locale=locale,
        currency=currency,
        timezone="UTC",
        status="ACTIVE",
    )
    session.add(club)
    await session.flush()

    session.add(ClubBranding(tenant_id=tenant.id, club_id=club.id))

    # A club with no address has no website, so one is issued here rather than
    # left as a later step somebody has to know about. The same call registers
    # it with the identity provider, which is what makes the sign-in button on
    # that new site actually work.
    await attach(session, tenant_id=tenant.id, club_id=club.id, hostname=hostname_for(slug))

    person = Person(
        id=new_id(),
        tenant_id=tenant.id,
        first_name=signup.first_name,
        last_name=signup.last_name,
        display_name=f"{signup.first_name} {signup.last_name}".strip(),
        preferred_locale=locale,
    )
    session.add(person)
    await session.flush()

    owner_role = await session.scalar(select(Role).where(Role.key == "TENANT_OWNER"))
    if owner_role is None:
        # The role templates are reference data seeded at deploy. Their absence
        # is a broken deployment, not a user error.
        raise ValidationFailed("The platform is not fully configured yet.")

    account = UserAccount(
        id=new_id(),
        subject_id=subject_id,
        email=signup.email,
        email_verified=not settings.require_email_verification,
        status="ACTIVE",
    )
    session.add(account)
    await session.flush()

    person.user_id = account.id
    session.add(
        RoleAssignment(
            id=new_id(),
            user_id=account.id,
            role_id=owner_role.id,
            tenant_id=tenant.id,
            valid_from=now,
        )
    )
    await session.flush()

    await _start_trial(session, tenant.id, now)

    log.info(
        "tenant_registered",
        tenant_id=str(tenant.id),
        slug=slug,
        country=tenant.country_code,
        locale=locale,
    )
    return Registered(
        tenant_id=str(tenant.id),
        club_id=str(club.id),
        club_slug=slug,
        email=signup.email,
    )


async def register(session: AsyncSession, signup: SignUp) -> Registered:
    """Sign up: a login, a tenant, a club and an owner.

    See the module docstring for why the identity provider goes first and what
    each failure leaves behind.
    """
    slug = validate_slug(signup.slug)
    validate_password(signup.password)

    # Checked before anything is created, so the common failure — a name
    # somebody already has — costs nothing and leaves nothing to undo. It is
    # not a lock: two simultaneous sign-ups for the same slug are settled by
    # the unique index below, and the loser gets the same message.
    if not await slug_available(session, slug):
        raise Conflict("That address is already taken.", field="slug")

    created = await get_admin().create_user(
        email=signup.email,
        password=signup.password,
        first_name=signup.first_name,
        last_name=signup.last_name,
    )

    try:
        return await _create_records(session, signup, created.subject_id)
    except Exception:
        # Compensate. The login exists and the tenant does not, so remove the
        # login — otherwise the address is registered to an account that can
        # never reach anything, and the person cannot even sign up again.
        await session.rollback()
        if await get_admin().delete_user(created.subject_id):
            log.info("registration_rolled_back", subject_id=created.subject_id)
        else:
            # Loud, because a human has to clean this up: the address is now
            # unusable for a second attempt until the login is removed.
            log.error(
                "registration_orphan_login",
                subject_id=created.subject_id,
                email=signup.email,
            )
        raise
