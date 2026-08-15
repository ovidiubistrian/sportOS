# 11 — Local Development Environment

## 1. Goal

```sh
git clone … && cd football-os
cp infrastructure/environments/.env.example .env
docker compose up
```

A new engineer has a working, seeded, multi-tenant environment in one command.
No local Postgres, Redis, Keycloak, Python or Node installation is required to
run the stack. (Node and uv are needed only for editor tooling and running tests
outside containers.)

## 2. Services

| Service | Image / build | URL | Purpose |
| --- | --- | --- | --- |
| `proxy` | caddy:2.9 | — | Host routing; on-demand TLS per club domain in production |
| `public-web` | build `apps/public-web` | `https://fcexample.localhost` | Next.js, club sites |
| `admin-web` | build `apps/admin-web` | `https://admin.footbola.localhost` | Staff SPA |
| `super-admin` | build `apps/super-admin` | `https://platform.footbola.localhost` | Platform SPA |
| `scanner` | build `apps/scanner` | `https://scan.footbola.localhost` | Scanner PWA |
| `api` | build `backend` | `https://api.footbola.localhost` | FastAPI, hot reload |
| `worker` | same image, Celery | — | Background jobs |
| `beat` | same image, Celery Beat | — | Scheduled jobs |
| `outbox-relay` | same image | — | Dispatches domain events, runs maintenance |
| `postgres` | postgres:17 | `:5432` | Primary datastore |
| `redis` | redis:7 | `:6379` | Cache, locks, broker |
| `keycloak` | keycloak:26 | `https://auth.footbola.localhost` | Identity |
| `minio` | minio | `https://files.footbola.localhost` | S3-compatible storage |
| `mailpit` | mailpit | `https://mail.footbola.localhost` | Captures all outbound email |
| `stripe-cli` | stripe/stripe-cli | — | Forwards real Stripe test webhooks |
| `jaeger` | jaegertracing all-in-one | `https://trace.footbola.localhost` | Traces (profile `observability`) |

### Why Caddy and `*.localhost`

Multi-tenancy is resolved by hostname. Testing that on `localhost:3000` is
impossible, and bugs in domain resolution would only appear in staging. Chrome,
Edge and Firefox resolve any `*.localhost` name to `127.0.0.1` automatically —
no `/etc/hosts` editing, no `nip.io` dependency — and treat it as a secure
context, so service workers, `Secure` cookies and `getUserMedia` all behave as
they will in production without a local CA.

Caddy rather than Traefik for one reason: clubs bring their own domains, and
each needs a certificate issued on first request without anyone touching
configuration. Caddy's on-demand TLS does that natively. It is guarded by an
`ask` endpoint (`/api/v1/public/domains/check`) that only approves hostnames
present and verified in `club_domain` — without it, anyone pointing DNS at us
could drive certificate requests until we hit the CA's per-account rate limit,
degrading every club at once. See `infrastructure/docker/caddy/`.

Two demo club domains are seeded (`fcexample.localhost`, `northern.localhost`)
so cross-tenant behaviour — and the fact that each club gets its own template
and palette — is visible constantly rather than tested once.

## 3. Compose profiles

```sh
docker compose up                         # core: proxy, api, worker, db, redis,
                                          # keycloak, minio, mailpit, admin-web
docker compose --profile full up          # + public-web, super-admin, scanner
docker compose --profile observability up # + jaeger, prometheus, grafana
docker compose --profile payments up      # + stripe-cli webhook forwarding
```

Default `up` starts what most work needs. Running all sixteen containers by
default costs ~6 GB of RAM and makes laptops unusable; that is a real, daily cost.

## 4. First-run automation

An `init` container runs once, ordered by health-check dependencies:

1. Wait for Postgres to be healthy
2. `alembic upgrade head`
3. Seed static reference data (permissions, role templates, features, plans,
   countries, currencies, tax classes)
4. Import the Keycloak realm from `infrastructure/docker/keycloak/realm-dev.json`
   (clients, flows, test users with known passwords)
5. Create MinIO buckets and policies
6. Seed the demo tenants (see §6)
7. Print a summary of URLs and login credentials to the console

Idempotent — a second run detects existing state and skips. Reset is
`docker compose down -v && docker compose up`.

## 5. Developer ergonomics

- **Backend hot reload**: source is bind-mounted, `uvicorn --reload`. Dependencies
  live in a named volume so a rebuild is not needed for a code change.
- **Frontend hot reload**: Vite and Next dev servers behind Caddy; HMR websockets
  are proxied on the same origin.
- **Debugging**: `debugpy` listens on `:5678` in the `api` container; VS Code and
  PyCharm launch configurations are checked in.
- **Database access**: exposed on `localhost:5432` for GUI clients.
- **Emails**: every outbound message lands in Mailpit. Nothing can escape to a
  real address from a dev environment — the SMTP host is hardcoded in the dev
  config and there is no fallback.
- **Stripe**: `stripe-cli` forwards test-mode webhooks to the local API, so the
  full payment flow including 3DS test cards works locally.

## 6. Demo data

`backend/app/platform/seeds/demo/` builds a realistic European second-division
club. It is generated from a deterministic seed, so everyone's environment
matches and screenshots are reproducible.

```
Tenant  "FC Example"  (Romania, ro + en + de, EUR, Europe/Bucharest)
└── Club "FC Example"
    ├── First team (26 players), Women's team, U19, U17, U15, U14, U13, U12,
    │   U11, U10, U9  (11 teams, 284 academy players)
    ├── 34 staff with realistic roles and 6 expiring qualifications
    ├── 412 guardians linked to academy players
    ├── Season 2025/26, 3 competitions, 38 fixtures (19 played with events)
    ├── Venue "Stadionul Example" — 4 stands, 2 seated (4 200 seats), 2 GA (3 000)
    ├── 12 400 supporters, 1 830 members, 940 season tickets
    ├── 3 ticketed events on sale, 2 past with ~7 000 scan records
    ├── 46 shop products with variants and stock
    ├── 2 fundraising campaigns, 28 news articles in 3 languages
    └── 9 sponsors across 4 tiers

Tenant  "Northern United"  (Germany, de + en, EUR)  — small, for isolation testing
Tenant  "Platform Demo"    — sandbox for sales demos
```

Two properties are deliberate:

- **Volume is realistic.** 284 players and 12 400 supporters, not six of each.
  Every list screen is therefore built and reviewed against data that paginates,
  filters slowly if indexed wrongly, and reveals layout problems with long names.
- **Demo data is labelled.** Every seeded row carries `source = 'DEMO'`, demo
  tenants are visually badged in super-admin, and a production safety check
  refuses to run the demo seeder against a non-development database.

## 7. Production differences (explicit)

Compose is a development tool. It is not the production topology.

| | Development | Production |
| --- | --- | --- |
| Postgres | Container | Managed, with automated backups + PITR |
| Redis | Container | Managed, persistence enabled |
| Object storage | MinIO | S3-compatible + CDN |
| Keycloak | Container, dev mode | Clustered, production mode, managed database |
| TLS | Local CA | ACME via the edge proxy / CDN |
| Secrets | `.env` | Secret manager, injected at runtime |
| Static frontends | Dev servers | Built assets on a CDN |
| Migrations | On startup | Explicit pipeline step, gated |

Running migrations on container start is convenient locally and dangerous in
production (N replicas racing, no rollback point). Production runs them as a
separate, gated pipeline step. See
[ADR-0010](../decisions/ADR-0010-deployment-topology.md).

## 8. Secrets

`.env.example` is committed with development-only placeholder values; `.env` is
git-ignored. A pre-commit hook runs `gitleaks`, and CI fails on any detected
secret. No real Stripe key, Keycloak client secret or storage credential ever
enters the repository — the development values are visibly fake
(`sk_test_DEVELOPMENT_ONLY_…`) so a leaked one is obviously worthless.
