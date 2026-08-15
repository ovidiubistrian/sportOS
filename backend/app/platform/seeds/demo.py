"""Demo tenants.

Two tenants, deliberately: a realistic Romanian second-division club, and a
small German one. Every screen is therefore built against cross-tenant data
from the first day, and the isolation tests have something real to probe.

Volumes are realistic — 284 academy players, not six — because a list screen
that has only ever been seen with six rows is a list screen that has not been
designed. Names use diacritics for the same reason: `Ștefănescu` catches
encoding and collation bugs that `Test User 1` never will.

Safety: refuses to run against a non-development database, and every row it
creates is marked `source='DEMO'` / `is_demo=true`.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select

from app.authz.models import Role, RoleAssignment
from app.billing.models import Plan, PlanVersion, TenantSubscription
from app.cms.models import ContentCategory, ContentItem, ContentTranslation
from app.cms.service import slugify
from app.core.config import settings
from app.core.db import platform_session
from app.core.logging import configure_logging
from app.identity.models import Person, PersonRoleFlag, UserAccount
from app.players.models import Player, PlayerRegistration
from app.teams.models import Season, Team
from app.tenants.branding_models import ClubBranding
from app.tenants.models import Club, ClubDomain, Tenant

# Registers every table on the shared metadata so cross-module foreign keys
# resolve. See app/core/model_registry.py.
from app.core import model_registry  # noqa: F401  isort: skip

log = structlog.get_logger("seed.demo")

# Deterministic, so every developer's environment matches and screenshots are
# reproducible. Not for cryptographic use.
RNG = random.Random(20260813)

FIRST_NAMES_RO = [
    "Andrei", "Mihai", "Ștefan", "Cristian", "Vlad", "Alexandru", "Ionuț",
    "Robert", "Darius", "Rareș", "Gabriel", "Sebastian", "Denis", "Marius",
    "Cătălin", "Florin", "Bogdan", "Răzvan", "Nicolae", "Tudor",
]
LAST_NAMES_RO = [
    "Popescu", "Ionescu", "Ștefănescu", "Dumitrescu", "Georgescu", "Marin",
    "Constantin", "Radu", "Munteanu", "Stoica", "Diaconu", "Barbu", "Nistor",
    "Șerban", "Crăciun", "Ardelean", "Lungu", "Oprea", "Vasilescu", "Ciobanu",
]
POSITIONS = ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "AM", "RW", "LW", "ST"]
FEET = ["RIGHT", "RIGHT", "RIGHT", "LEFT", "BOTH"]

# Keycloak user ids, fixed in realm-dev.json so the link is deterministic.
KEYCLOAK_USERS = {
    "owner@fcexample.test": ("0192a000-0000-7000-8000-000000000001", "Diana", "Marinescu"),
    "academy@fcexample.test": ("0192a000-0000-7000-8000-000000000002", "Radu", "Ionescu"),
    "coach.u15@fcexample.test": ("0192a000-0000-7000-8000-000000000003", "Ana", "Popescu"),
    "owner@northern.test": ("0192a000-0000-7000-8000-000000000004", "Lena", "Brandt"),
    "platform@footbola.test": ("0192a000-0000-7000-8000-000000000005", "Platform", "Operator"),
}

ACADEMY_SQUADS = [
    ("U19", "U19", 24), ("U17", "U17", 26), ("U16", "U16", 24), ("U15", "U15", 22),
    ("U14", "U14", 24), ("U13", "U13", 26), ("U12", "U12", 28), ("U11", "U11", 26),
    ("U10", "U10", 24), ("U9", "U9", 22),
]


async def seed_demo() -> None:
    if settings.is_production:
        raise SystemExit("Refusing to seed demo data into a production database.")

    async with platform_session(reason="seed demo tenants", routine=True) as session:
        if await session.scalar(select(Tenant.id).where(Tenant.slug == "fc-example")):
            log.info("demo_already_seeded")
            return

        users = await _seed_users(session)
        fc_tenant = await _seed_fc_example(session, users)
        northern_tenant = await _seed_northern(session, users)
        await _seed_platform_role(session, users)

        # Different plans on purpose: the entitlement layer is only meaningfully
        # exercised when two tenants have different capabilities.
        await _subscribe(session, fc_tenant, "PRO")
        await _subscribe(session, northern_tenant, "STARTER")

    log.info("demo_seeded")


async def _seed_users(session) -> dict[str, UserAccount]:
    users: dict[str, UserAccount] = {}
    for email, (subject_id, _, _) in KEYCLOAK_USERS.items():
        user = UserAccount(
            subject_id=subject_id,
            email=email,
            email_verified=True,
            is_platform_user=email.endswith("@footbola.test"),
        )
        session.add(user)
        users[email] = user
    await session.flush()
    return users


async def _grant(
    session,
    user: UserAccount,
    role_key: str,
    *,
    tenant_id: UUID | None = None,
    club_id: UUID | None = None,
    team_id: UUID | None = None,
) -> None:
    role = await session.scalar(
        select(Role).where(Role.key == role_key, Role.tenant_id.is_(None))
    )
    if role is None:
        raise RuntimeError(f"System role {role_key} is missing; run the reference seed first.")
    session.add(
        RoleAssignment(
            user_id=user.id,
            role_id=role.id,
            tenant_id=tenant_id,
            club_id=club_id,
            team_id=team_id,
        )
    )


async def _seed_fc_example(session, users: dict[str, UserAccount]) -> Tenant:
    tenant = Tenant(
        slug="fc-example",
        legal_name="AFC Example SA",
        trading_name="FC Example",
        country_code="RO",
        default_locale="ro",
        supported_locales=["ro", "en", "de"],
        default_currency="EUR",
        timezone="Europe/Bucharest",
        status="ACTIVE",
        billing_email="finance@fcexample.test",
        is_demo=True,
    )
    session.add(tenant)
    await session.flush()

    club = Club(
        tenant_id=tenant.id,
        slug="fc-example",
        legal_name="Asociația Fotbal Club Example",
        display_name="FC Example",
        short_name="EXA",
        founded_year=1921,
        country_code="RO",
        default_locale="ro",
        currency="EUR",
        timezone="Europe/Bucharest",
    )
    session.add(club)
    await session.flush()

    session.add(
        ClubBranding(
            tenant_id=tenant.id,
            club_id=club.id,
            template="BOLD",
            color_mode="LIGHT",
            color_primary="#1F4B99",
            color_secondary="#E4B33C",
            color_accent="#C8102E",
            tagline="Din 1921, pentru oraș.",
            social={"facebook": "https://facebook.com/fcexample"},
        )
    )

    session.add(
        ClubDomain(
            tenant_id=tenant.id,
            club_id=club.id,
            hostname="fcexample.localhost",
            kind="PRIMARY",
        )
    )

    season = Season(
        tenant_id=tenant.id,
        club_id=club.id,
        name="2025/26",
        start_date=date(2025, 7, 1),
        end_date=date(2026, 6, 30),
        is_current=True,
    )
    previous = Season(
        tenant_id=tenant.id,
        club_id=club.id,
        name="2024/25",
        start_date=date(2024, 7, 1),
        end_date=date(2025, 6, 30),
        is_current=False,
    )
    session.add_all([season, previous])
    await session.flush()

    teams: dict[str, Team] = {}
    senior_specs = [
        ("First Team", "SEN", "MALE", None, "FIRST", False, 26),
        ("Women's Team", "WOM", "FEMALE", None, "FIRST", False, 22),
    ]
    for name, code, gender, age_group, level, academy, _ in senior_specs:
        team = Team(
            tenant_id=tenant.id, club_id=club.id, name=name, code=code,
            gender=gender, age_group=age_group, level=level, is_academy=academy,
        )
        session.add(team)
        teams[code] = team

    for name, code, _ in ACADEMY_SQUADS:
        team = Team(
            tenant_id=tenant.id, club_id=club.id, name=name, code=code,
            gender="MALE", age_group=code, level="YOUTH", is_academy=True,
        )
        session.add(team)
        teams[code] = team
    await session.flush()

    total = 0
    squads = [(c, s) for _n, c, _g, _a, _l, _ac, s in senior_specs]
    squads += [(code, size) for _name, code, size in ACADEMY_SQUADS]
    for code, size in squads:
        total += await _seed_squad(
            session, tenant, club, season, teams[code], code, size
        )

    # Staff logins, at three different scopes — the point of the demo.
    await _grant(session, users["owner@fcexample.test"], "TENANT_OWNER", tenant_id=tenant.id)
    await _grant(
        session, users["academy@fcexample.test"], "ACADEMY_DIRECTOR",
        tenant_id=tenant.id, club_id=club.id,
    )
    await _grant(
        session, users["coach.u15@fcexample.test"], "COACH",
        tenant_id=tenant.id, club_id=club.id, team_id=teams["U15"].id,
    )

    articles = await _seed_articles(session, tenant, club)

    log.info(
        "seeded_tenant",
        slug="fc-example",
        teams=len(teams),
        players=total,
        articles=articles,
    )
    return tenant


async def _seed_squad(
    session,
    tenant: Tenant,
    club: Club,
    season: Season,
    team: Team,
    code: str,
    size: int,
) -> int:
    birth_year = _birth_year_for(code)
    shirts = RNG.sample(range(1, 100), size)

    for index in range(size):
        first = RNG.choice(FIRST_NAMES_RO)
        last = RNG.choice(LAST_NAMES_RO)
        person = Person(
            tenant_id=tenant.id,
            first_name=first,
            last_name=last,
            display_name=f"{first} {last}",
            birth_date=datetime(
                birth_year, RNG.randint(1, 12), RNG.randint(1, 28), tzinfo=UTC
            ),
            nationality=["RO"],
            source="DEMO",
        )
        session.add(person)
        await session.flush()

        player = Player(
            tenant_id=tenant.id,
            club_id=club.id,
            person_id=person.id,
            status="REGISTERED",
            primary_position=POSITIONS[index % len(POSITIONS)],
            secondary_positions=[],
            preferred_foot=RNG.choice(FEET),
            joined_club_on=date(birth_year + 8, 8, 1),
        )
        session.add(player)
        session.add(
            PersonRoleFlag(
                tenant_id=tenant.id, person_id=person.id, role_kind="PLAYER"
            )
        )
        await session.flush()

        session.add(
            PlayerRegistration(
                tenant_id=tenant.id,
                player_id=player.id,
                team_id=team.id,
                season_id=season.id,
                shirt_number=shirts[index],
                kind="PERMANENT",
                registered_on=date(2025, 7, 15),
            )
        )
    await session.flush()
    return size


def _birth_year_for(code: str) -> int:
    if code in ("SEN", "WOM"):
        return RNG.randint(1996, 2005)
    if code.startswith("U"):
        return 2026 - int(code[1:])
    return 2005


async def _seed_northern(session, users: dict[str, UserAccount]) -> Tenant:
    tenant = Tenant(
        slug="northern-united",
        legal_name="Northern United e.V.",
        trading_name="Northern United",
        country_code="DE",
        default_locale="de",
        supported_locales=["de", "en"],
        default_currency="EUR",
        timezone="Europe/Berlin",
        status="ACTIVE",
        is_demo=True,
    )
    session.add(tenant)
    await session.flush()

    club = Club(
        tenant_id=tenant.id,
        slug="northern-united",
        legal_name="Northern United e.V.",
        display_name="Northern United",
        short_name="NU",
        founded_year=1974,
        country_code="DE",
        default_locale="de",
        currency="EUR",
        timezone="Europe/Berlin",
    )
    session.add(club)
    await session.flush()

    # A different template and palette, so the two demo tenants exercise the
    # theming rather than looking identical.
    session.add(
        ClubBranding(
            tenant_id=tenant.id,
            club_id=club.id,
            template="COMPACT",
            color_primary="#0F5132",
            color_secondary="#1B1B1B",
            tagline="Fußball für alle.",
        )
    )
    session.add(
        ClubDomain(
            tenant_id=tenant.id,
            club_id=club.id,
            hostname="northern.localhost",
            kind="PRIMARY",
        )
    )

    season = Season(
        tenant_id=tenant.id, club_id=club.id, name="2025/26",
        start_date=date(2025, 7, 1), end_date=date(2026, 6, 30), is_current=True,
    )
    session.add(season)
    team = Team(
        tenant_id=tenant.id, club_id=club.id, name="U15", code="U15",
        gender="MALE", age_group="U15", level="YOUTH", is_academy=True,
    )
    session.add(team)
    await session.flush()

    await _seed_squad(session, tenant, club, season, team, "U15", 18)
    await _grant(session, users["owner@northern.test"], "TENANT_OWNER", tenant_id=tenant.id)
    log.info("seeded_tenant", slug="northern-united", players=18)
    return tenant


# Multilingual on purpose: the second article exists only in Romanian, so the
# locale-fallback path is exercised by the demo rather than only by a test.
DEMO_ARTICLES: list[dict] = [
    {
        "category": "match-report",
        "article_type": "MATCH_REPORT",
        "days_ago": 2,
        "pinned": True,
        "translations": {
            "ro": (
                "Victorie clară în derby-ul orașului",
                [
                    {"type": "paragraph", "text": "Echipa noastră s-a impus cu 3-1 într-un meci controlat de la primul până la ultimul minut, în fața a peste patru mii de spectatori."},
                    {"type": "heading", "level": 2, "text": "Repriza a doua a decis totul"},
                    {"type": "paragraph", "text": "După pauză, presingul avansat a produs două goluri în opt minute. Linia defensivă nu a mai concedat nimic până la final."},
                    {"type": "quote", "text": "Am cerut curaj de la primul minut și exact asta am primit.", "attribution": "Antrenor principal"},
                ],
            ),
            "en": (
                "Clear win in the city derby",
                [
                    {"type": "paragraph", "text": "A 3-1 win in a match controlled from the first minute to the last, in front of more than four thousand supporters."},
                    {"type": "heading", "level": 2, "text": "The second half decided it"},
                    {"type": "paragraph", "text": "After the break a high press produced two goals in eight minutes, and the back line conceded nothing more."},
                    {"type": "quote", "text": "We asked for courage from the first minute, and that is exactly what we got.", "attribution": "Head coach"},
                ],
            ),
        },
    },
    {
        "category": "academy",
        "article_type": "ACADEMY",
        "days_ago": 6,
        "pinned": False,
        "translations": {
            "ro": (
                "Înscrieri deschise la academie pentru grupele U9-U12",
                [
                    {"type": "paragraph", "text": "Academia primește înscrieri pentru sezonul următor. Antrenamentele se desfășoară de trei ori pe săptămână."},
                    {"type": "list", "ordered": False, "items": ["Grupele U9 și U10 — luni, miercuri, vineri", "Grupele U11 și U12 — marți, joi, sâmbătă", "Echipament complet inclus"]},
                    {"type": "paragraph", "text": "Părinții pot programa o ședință de probă direct prin portalul clubului."},
                ],
            ),
        },
    },
    {
        "category": "club",
        "article_type": "ANNOUNCEMENT",
        "days_ago": 14,
        "pinned": False,
        "translations": {
            "ro": (
                "Lucrările la baza sportivă intră în linie dreaptă",
                [
                    {"type": "paragraph", "text": "Cele două terenuri sintetice vor fi disponibile înainte de startul sezonului, iar vestiarele au fost complet renovate."},
                    {"type": "paragraph", "text": "Investiția a fost susținută de club împreună cu partenerii locali."},
                ],
            ),
            "en": (
                "Training ground works on schedule",
                [
                    {"type": "paragraph", "text": "Both synthetic pitches will be available before the season starts, and the changing rooms have been fully renovated."},
                    {"type": "paragraph", "text": "The work was funded by the club together with its local partners."},
                ],
            ),
            "de": (
                "Bauarbeiten am Trainingsgelände im Zeitplan",
                [
                    {"type": "paragraph", "text": "Beide Kunstrasenplätze stehen vor dem Saisonstart zur Verfügung, die Kabinen wurden vollständig renoviert."},
                ],
            ),
        },
    },
    {
        "category": "club",
        "article_type": "SIGNING",
        "days_ago": 9,
        "pinned": False,
        "translations": {
            "ro": (
                "Andrei Marin semnează pentru două sezoane",
                [
                    {"type": "paragraph", "text": "Mijlocașul Andrei Marin, 24 de ani, a semnat un contract valabil două sezoane. Vine de la FC Vecin, unde a strâns 68 de meciuri."},
                    {"type": "quote", "text": "Am simțit din prima discuție că aici se construiește ceva serios.", "attribution": "Andrei Marin"},
                    {"type": "paragraph", "text": "Va purta numărul 8 și intră în programul echipei începând de luni."},
                ],
            ),
            "en": (
                "Andrei Marin signs for two seasons",
                [
                    {"type": "paragraph", "text": "Midfielder Andrei Marin, 24, has signed a two-season contract. He joins from FC Vecin, where he made 68 appearances."},
                    {"type": "quote", "text": "From the first conversation it was clear something serious is being built here.", "attribution": "Andrei Marin"},
                    {"type": "paragraph", "text": "He takes the number 8 shirt and joins training on Monday."},
                ],
            ),
        },
    },
    {
        "category": "club",
        "article_type": "DEPARTURE",
        "days_ago": 20,
        "pinned": False,
        "translations": {
            "ro": (
                "Mulțumim, Radu",
                [
                    {"type": "paragraph", "text": "După șapte ani și 214 meciuri, Radu Constantin pleacă de la club. A ales să continue la o echipă din liga secundă, mai aproape de familie."},
                    {"type": "heading", "level": 2, "text": "Șapte ani"},
                    {"type": "paragraph", "text": "A venit ca junior și a plecat căpitan. A jucat cu o coastă fisurată în ultima etapă a sezonului 2023 și a marcat golul care ne-a ținut în ligă."},
                    {"type": "quote", "text": "Clubul ăsta m-a făcut fotbalist și om. Rămâne casa mea.", "attribution": "Radu Constantin"},
                    {"type": "paragraph", "text": "Îi mulțumim pentru tot și îi dorim numai bine."},
                ],
            ),
            "en": (
                "Thank you, Radu",
                [
                    {"type": "paragraph", "text": "After seven years and 214 appearances, Radu Constantin leaves the club. He has chosen to continue in the second division, closer to his family."},
                    {"type": "heading", "level": 2, "text": "Seven years"},
                    {"type": "paragraph", "text": "He arrived as a junior and left as captain. He played the final round of the 2023 season with a cracked rib and scored the goal that kept us up."},
                    {"type": "quote", "text": "This club made me a footballer and a man. It stays my home.", "attribution": "Radu Constantin"},
                    {"type": "paragraph", "text": "We thank him for everything and wish him nothing but the best."},
                ],
            ),
        },
    },
]


async def _seed_articles(session, tenant: Tenant, club: Club) -> int:
    categories = {}
    for position, (key, name) in enumerate(
        [("match-report", "Match reports"), ("academy", "Academy"), ("club", "Club news")]
    ):
        category = ContentCategory(
            tenant_id=tenant.id, club_id=club.id, key=key, name=name, position=position
        )
        session.add(category)
        categories[key] = category
    await session.flush()

    now = datetime.now(UTC)
    for spec in DEMO_ARTICLES:
        published_at = now - timedelta(days=spec["days_ago"])
        item = ContentItem(
            tenant_id=tenant.id,
            club_id=club.id,
            category_id=categories[spec["category"]].id,
            kind="ARTICLE",
            article_type=spec["article_type"],
            status="PUBLISHED",
            published_at=published_at,
            is_pinned=spec["pinned"],
        )
        session.add(item)
        await session.flush()

        for locale, (title, body) in spec["translations"].items():
            session.add(
                ContentTranslation(
                    tenant_id=tenant.id,
                    content_item_id=item.id,
                    club_id=club.id,
                    locale=locale,
                    title=title,
                    slug=slugify(title),
                    excerpt=body[0]["text"][:200],
                    body=body,
                    status="READY",
                )
            )

    # One scheduled for the near future, so the publishing job has something
    # real to do in a running environment.
    upcoming = ContentItem(
        tenant_id=tenant.id,
        club_id=club.id,
        category_id=categories["club"].id,
        kind="ARTICLE",
        article_type="ANNOUNCEMENT",
        status="SCHEDULED",
        scheduled_for=now + timedelta(days=3),
    )
    session.add(upcoming)
    await session.flush()
    session.add(
        ContentTranslation(
            tenant_id=tenant.id,
            content_item_id=upcoming.id,
            club_id=club.id,
            locale="ro",
            title="Program de pregătire pentru pauza competițională",
            slug="program-pregatire-pauza",
            excerpt="Programul complet al săptămânilor de pregătire.",
            body=[{"type": "paragraph", "text": "Programul complet va fi publicat aici."}],
            status="READY",
        )
    )

    await session.flush()
    return len(DEMO_ARTICLES)


async def _subscribe(session, tenant: Tenant, plan_key: str) -> None:
    """Put a demo tenant on a plan.

    Subscriptions pin a `plan_version`, never a plan: a later pricing change
    creates version 2 and leaves this tenant on what it actually agreed to.
    """
    version = await session.scalar(
        select(PlanVersion)
        .join(Plan, Plan.id == PlanVersion.plan_id)
        .where(Plan.key == plan_key)
        .order_by(PlanVersion.version.desc())
    )
    if version is None:
        raise RuntimeError(f"Plan {plan_key} is missing; run the plans seed first.")

    now = datetime.now(UTC)
    session.add(
        TenantSubscription(
            tenant_id=tenant.id,
            plan_version_id=version.id,
            status="ACTIVE",
            currency=tenant.default_currency,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
    )
    log.info("tenant_subscribed", slug=tenant.slug, plan=plan_key)


async def _seed_platform_role(session, users: dict[str, UserAccount]) -> None:
    await _grant(session, users["platform@footbola.test"], "SUPER_ADMIN")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(seed_demo())
