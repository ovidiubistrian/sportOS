# 01 — Monorepo Structure

## 1. Layout

```
football-os/
├── apps/
│   ├── public-web/            Next.js 15 — club public sites (multi-domain)
│   ├── admin-web/             React SPA — club/tenant staff back office
│   ├── super-admin/           React SPA — platform operations
│   └── scanner/               React PWA — matchday access control
│
├── backend/
│   ├── app/
│   │   ├── main.py            ASGI app factory, router mounting
│   │   ├── worker.py          Celery app
│   │   ├── core/              config, db session, security, errors, pagination,
│   │   │                      tenant context, telemetry, money, ids, clock
│   │   ├── platform/          super-admin surface: tenants, plans, entitlements,
│   │   │                      impersonation, platform analytics
│   │   ├── identity/          users, sessions, OIDC, role assignments
│   │   ├── tenants/           tenant + settings + domains + branding
│   │   ├── clubs/             clubs, departments, seasons, facilities
│   │   ├── people/            person registry, contact details, dedup
│   │   ├── staff/             staff profiles, qualifications, expiry alerts
│   │   ├── teams/             teams, team-season rosters
│   │   ├── academy/           age groups, registrations, fees
│   │   ├── players/           player profiles, registrations, documents
│   │   ├── guardians/         guardian links, parental consent
│   │   ├── training/          sessions, drills, attendance, periodisation
│   │   ├── development/       evaluation frameworks, evaluations, IDPs
│   │   ├── medical/           medical records, injuries, availability projection
│   │   ├── competitions/      competitions, competition seasons, standings
│   │   ├── matches/           fixtures, squads, lineups, events, stats
│   │   ├── scouting/          prospects, reports, watchlists
│   │   ├── venues/            venues, stands, sections, rows, seats, gates
│   │   ├── ticketing/         events, ticket types, inventory, holds, tickets
│   │   ├── access_control/    credentials, scanning, offline manifests, devices
│   │   ├── fans/              fan profiles, preferences, segmentation
│   │   ├── memberships/       plans, benefits, memberships, season tickets
│   │   ├── loyalty/           programs, ledger, tiers, rewards
│   │   ├── commerce/          catalogue, inventory, cart, orders, fulfilment
│   │   ├── fundraising/       campaigns, donations, receipts
│   │   ├── payments/          provider port, Stripe adapter, webhooks, refunds
│   │   ├── billing/           plans, subscriptions, billing policies, fees
│   │   ├── cms/               content, translations, navigation, publishing
│   │   ├── media/             uploads, storage port, image processing
│   │   ├── sponsorship/       sponsors, contracts, placements
│   │   ├── notifications/     templates, channels, dispatch, preferences
│   │   ├── analytics/         read models, aggregation jobs, reports
│   │   ├── audit/             audit log writer + query surface
│   │   ├── privacy/           consent, export, erasure, retention
│   │   └── integrations/      outbound third-party adapters
│   ├── migrations/            Alembic
│   ├── tests/                 cross-module: isolation, permissions, e2e-api
│   ├── pyproject.toml
│   └── Dockerfile
│
├── packages/
│   ├── ui/                    design system: tokens, primitives, patterns
│   ├── api-client/            generated from OpenAPI + typed fetch wrapper
│   ├── auth/                  OIDC client, session hooks, permission guards
│   ├── i18n/                  ICU message catalogues, locale utilities
│   ├── types/                 hand-written cross-app types (non-API)
│   ├── validation/            shared Zod schemas mirroring API contracts
│   └── config/                eslint, tsconfig, tailwind preset, prettier
│
├── infrastructure/
│   ├── docker/                per-service Dockerfiles and entrypoints
│   └── environments/          .env.example, compose overrides, deploy manifests
│
├── docs/
│   ├── architecture/
│   ├── decisions/             ADRs
│   └── api/                   generated OpenAPI snapshots + guides
│
├── docker-compose.yml
├── package.json               pnpm workspace root
├── pnpm-workspace.yaml
├── turbo.json
└── README.md
```

## 2. Module internal structure (backend)

Every backend module follows the same shape. Consistency here is worth more than
per-module cleverness — an engineer who has read one module can navigate all of
them.

```
app/ticketing/
├── __init__.py
├── models.py           SQLAlchemy mapped classes (or models/ package if > ~400 lines)
├── schemas.py          Pydantic request/response models
├── repository.py       Data access. Returns entities, never leaks Session upward.
├── services/           Business logic, one file per use-case cluster
│   ├── inventory.py
│   ├── purchase.py
│   └── refunds.py
├── router.py           FastAPI routes. Thin: parse → authorise → call service → serialise
├── permissions.py      Permission keys owned by this module
├── events.py           Domain events this module publishes
├── handlers.py         Domain events this module consumes
├── tasks.py            Celery tasks owned by this module
├── errors.py           Domain exceptions
└── tests/
    ├── test_services.py
    ├── test_repository.py
    └── test_api.py
```

Rules:

- **Routers contain no business logic.** A router may: validate input, resolve
  context, call one service method, map the result to a response schema. If a
  router has an `if` about domain state, it is misplaced.
- **Repositories contain no business rules**, only queries and persistence.
- **Services do not import another module's repository or models.** They call the
  other module's *service* interface, or react to its domain events.
- **No `app/services/` global folder.** No `app/models.py` god-file.
- `app/core/` may be imported by anything; it must import nothing from modules.

## 3. Tooling

| Concern | Tool | Why |
| --- | --- | --- |
| JS package manager | pnpm workspaces | Strict node_modules, fast, first-class monorepo |
| JS task orchestration | Turborepo | Cached builds; keeps CI under a few minutes |
| Python packaging | uv + `pyproject.toml` | Fast, reproducible lockfile, single tool |
| Python lint/format | Ruff (lint + format) | One tool replaces flake8/isort/black |
| Python types | mypy strict on `app/`, ratcheted per module | |
| TS lint/format | ESLint flat config + Prettier, shared from `packages/config` | |
| Import boundaries (Py) | `import-linter` contracts in CI | See [02](02-domain-boundaries.md) |
| Import boundaries (TS) | ESLint `no-restricted-imports` + project references | |
| Commits | Conventional Commits; changesets not needed (no published packages) | |

Node 22 LTS, Python 3.12+, pnpm 9+.

## 4. Why a single repository

- The OpenAPI schema is generated by the backend and consumed by four frontends.
  In split repos, every API change becomes a cross-repo dance with version drift.
  Here, a contract change and its consumers land in one commit and CI catches
  breakage immediately.
- Shared design system, i18n catalogues and validation schemas are consumed by
  every app.
- One CI pipeline, one version of truth for environment configuration.

Cost: CI must be path-filtered or it will run everything on every commit.
Turborepo's affected-graph plus GitHub Actions path filters handle this; budget
is < 8 minutes for a full pipeline, < 4 for a typical PR.

## 5. Ownership boundaries for a small team

`CODEOWNERS` is set up per top-level area rather than per module, so review load
stays realistic:

```
/backend/app/ticketing/       @backend @payments-reviewers
/backend/app/access_control/  @backend @payments-reviewers
/backend/app/payments/        @payments-reviewers
/backend/app/billing/         @payments-reviewers
/backend/app/medical/         @privacy-reviewers
/backend/app/privacy/         @privacy-reviewers
/packages/ui/                 @design-system
/docs/decisions/              @architects
```

Money, medical data and privacy always get a second reviewer. That is the only
mandatory-review rule; everything else is normal team flow.
