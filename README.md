# Football Club OS

Multi-tenant SaaS platform for football clubs: club & academy management, player
development, matches, ticketing, memberships, fan CRM, commerce, fundraising,
public websites and platform administration.

> **Status: vertical slice.** The architecture in `docs/architecture/` is agreed,
> and one path is implemented end to end to prove it: Docker Compose → Keycloak
> login → tenant/club/team/player through migrations, RLS, scoped RBAC and the
> API → an admin UI. Phase 0 (see [the roadmap](docs/architecture/16-roadmap.md))
> broadens this foundation; Phase 1 builds the product on it.

## Documentation map

| Document | Contents |
| --- | --- |
| [00 — Overview](docs/architecture/00-overview.md) | System context, quality attributes, scale targets |
| [01 — Monorepo structure](docs/architecture/01-monorepo-structure.md) | Directory layout, tooling, ownership |
| [02 — Domain boundaries](docs/architecture/02-domain-boundaries.md) | Modules, dependency rules, enforcement |
| [03 — Data model](docs/architecture/03-data-model.md) | Entity model per domain, constraints, indexes |
| [04 — Multitenancy](docs/architecture/04-multitenancy.md) | Tenant context, RLS, isolation testing |
| [05 — Identity & authentication](docs/architecture/05-identity-and-authentication.md) | Keycloak topology, User/Person split, sessions |
| [06 — Authorization](docs/architecture/06-authorization.md) | Scoped RBAC, permission resolution, medical/finance guards |
| [07 — Entitlements](docs/architecture/07-entitlements.md) | Feature flags, plan-driven capabilities, enforcement |
| [08 — SaaS billing](docs/architecture/08-saas-billing.md) | Plans, billing policies, platform fees, revenue recognition |
| [09 — Payments](docs/architecture/09-payments.md) | Provider abstraction, Stripe Connect, refunds, VAT |
| [10 — Events & outbox](docs/architecture/10-events-and-outbox.md) | Domain events, transactional outbox, consumer idempotency |
| [11 — Local environment](docs/architecture/11-local-environment.md) | Docker Compose topology, first-run workflow |
| [12 — API conventions](docs/architecture/12-api-conventions.md) | Versioning, pagination, errors, idempotency, concurrency |
| [13 — Frontend architecture](docs/architecture/13-frontend-architecture.md) | Four apps, shared packages, data layer, i18n |
| [14 — Design system](docs/architecture/14-design-system.md) | Tokens, primitives, layout patterns, branding limits |
| [15 — Testing strategy](docs/architecture/15-testing-strategy.md) | Test pyramid, mandatory suites, CI gates |
| [16 — Roadmap](docs/architecture/16-roadmap.md) | Phase breakdown, sequencing, exit criteria |
| [17 — Newsroom & assistant](docs/architecture/17-newsroom-and-assistant.md) | Articles, translations, article types, the AI writing assistant |
| [18 — Languages & countries](docs/architecture/18-languages-and-countries.md) | Interface vs content language, adding a locale, currency and timezone |
| [Open questions](docs/architecture/open-questions.md) | Contradictions and decisions requiring sign-off |

Architecture Decision Records live in [`docs/decisions/`](docs/decisions/).

## Repository layout

See [01 — Monorepo structure](docs/architecture/01-monorepo-structure.md). Summary:

```
apps/         public-web (Next.js), admin-web, super-admin, scanner (Vite SPAs)
backend/      FastAPI modular monolith + Alembic migrations + tests
packages/     ui, api-client, auth, i18n, types, validation, config
infrastructure/ docker, environments
docs/         architecture, decisions, api
```

## Getting started

Everything runs in Docker Compose — no local Postgres, Redis, Keycloak, Python
or Node installation required.

```sh
cp infrastructure/environments/.env.example .env
docker compose up
```

First run applies migrations, seeds reference data and builds two demo tenants
(~5 minutes, mostly image pulls). Then:

| | |
| --- | --- |
| Admin | http://admin.footbola.localhost |
| API docs | http://api.footbola.localhost/docs |
| Keycloak | http://auth.footbola.localhost |
| Mail (Mailpit) | http://mail.footbola.localhost |
| Traefik | http://localhost:8090 |

`*.localhost` resolves to 127.0.0.1 automatically in Chrome, Edge and Firefox —
no `/etc/hosts` editing.

### Development sign-ins

All use the password `password`. They exist to make scoping visible: sign in as
the coach and the player list is 22 rows, not 294.

| Account | Role | Sees |
| --- | --- | --- |
| `owner@fcexample.test` | Tenant Owner | 294 players, all 12 teams |
| `academy@fcexample.test` | Academy Director (club) | The whole academy |
| `coach.u15@fcexample.test` | Coach (U15 only) | 22 players, U15 only |
| `owner@northern.test` | Tenant Owner, other tenant | 18 players, nothing from FC Example |
| `platform@footbola.test` | Platform Super Admin | Platform surface |

### Common commands

```sh
docker compose exec api pytest              # backend suite (120 tests)
docker compose exec api ruff check app tests
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "message"
docker compose down -v && docker compose up # full reset
```

Host ports for Postgres and Redis are configurable in `.env`
(`POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`) so the stack coexists with other
projects.

Full details: [11 — Local environment](docs/architecture/11-local-environment.md).

## What the slice proves

- **Tenant isolation, four layers deep.** Request context → repository base
  class → PostgreSQL RLS (the runtime role has no `BYPASSRLS`) → composite
  tenant foreign keys. With no tenant bound, queries return zero rows rather
  than leaking; a cross-tenant `INSERT` is rejected by the database itself.
- **Scoped RBAC.** A U15 coach reads 22 players; the same endpoint returns 294
  to the tenant owner. A player in another team is `404`, never `403`.
- **Generated test suites.** The permission matrix and cross-tenant probe are
  derived from the OpenAPI schema, so a new route without an entry fails CI
  instead of shipping unchecked.
- **Events cannot be lost.** A domain event is written in the same transaction
  as the change that caused it; a separate relay process delivers it with
  `FOR UPDATE SKIP LOCKED`, and every handler claims its event so at-least-once
  delivery is safe.
- **Audit fails closed.** Only fields on a per-object-type allow-list are ever
  recorded, so adding a column never starts leaking it.
- **Entitlements gate the server, not the UI.** Turning off a feature turns a
  working endpoint into a `402` with an upgrade hint; no module may branch on a
  plan name, and an `ast`-based test enforces it.
- **A newsroom, in every language the club publishes.** One article, many
  translations, one lifecycle: an article can be live in Romanian while the
  German version is still being written, and the editor can see exactly that.
  Bodies are typed blocks rather than HTML, so the four site templates each
  render them in their own character and stored XSS has nowhere to live.
- **A writing assistant on one platform-held key.** Every tenant uses the same
  key; who may use it and how much is per-tenant entitlement policy, set by the
  super admin with a mandatory reason and metered per call. The assistant
  proposes — the editor sees the suggestion side by side and decides. See
  [ADR-0011](docs/decisions/ADR-0011-ai-writing-assistant.md).

## Licence

Proprietary. All rights reserved.
