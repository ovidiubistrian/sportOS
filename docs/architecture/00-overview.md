# 00 — System Overview

## 1. What this system is

Football Club OS is a multi-tenant SaaS platform that runs the operational and
commercial life of a football club: the sporting side (academy, teams, players,
training, matches, development), the commercial side (ticketing, memberships,
commerce, donations, sponsorship) and the audience side (public website, fan
accounts, CRM, loyalty) — plus the platform business that sells it.

It is one product with three distinct user populations, and that shapes almost
every architectural decision:

| Population | Volume per tenant | Access pattern | Latency tolerance |
| --- | --- | --- | --- |
| Staff (coaches, admins, ticketing, medical) | 10–200 | Dense operational UI, working hours | Interactive (< 300 ms p95) |
| Fans (supporters, members, parents) | 5 000 – 50 000 | Bursty, spiking on ticket release and matchday | Interactive, burst-tolerant |
| Stewards at the gate | 5–40 devices | Extreme burst, 60–90 min window, hostile network | **< 150 ms, must work offline** |

The third row is the one that constrains us most. Everything about the ticketing
and access-control design follows from "the stadium Wi-Fi will fail during the
90 minutes when it matters most".

## 2. Scale targets (pilot and 3-year horizon)

Design targets, not aspirations. These are the numbers the data model, indexes
and capacity plan are sized against.

| Dimension | Pilot (1 tenant) | Year 3 (platform) |
| --- | --- | --- |
| Tenants | 1 | 300 |
| Clubs | 1 | 400 |
| Teams per club | 10–20 | 20 |
| Academy players | 200–500 | 120 000 |
| Registered supporters | 5 000 – 20 000 | 2 500 000 |
| Tickets per match | 3 000 – 8 000 | — |
| Peak ticket-sale rate | 30 orders/sec | 200 orders/sec |
| Peak scan rate | 15 scans/sec sustained, 40 burst | — |
| Rows in largest table (`audit_log`, `ticket_scan`) | 10⁶ | 10⁹ (partitioned) |

At year-3 volumes a single well-indexed PostgreSQL primary with read replicas is
still comfortably sufficient. Nothing here justifies sharding, microservices, a
message broker beyond Redis, or a search cluster. We revisit if a *measured*
constraint appears.

## 3. Architectural style

**Modular monolith.** One deployable FastAPI application composed of vertically
sliced domain modules with enforced dependency rules, plus one worker deployable
running the same codebase. See [02 — Domain boundaries](02-domain-boundaries.md).

Rationale, and what we give up:

- A team of 3–8 engineers cannot operate 20 services. Distributed transactions
  across ticketing/payments/loyalty would be the dominant source of production
  incidents.
- Ticket purchase spans inventory, orders, payments, credentials and loyalty. In
  a monolith that is one database transaction plus an outbox row. Across services
  it is a saga with compensating actions. The monolith is not a compromise here —
  it is the *correct* consistency model for this domain.
- What we give up: independent scaling and independent deploy cadence per module.
  We mitigate by running the same image in differently-sized deployments (API,
  worker, and — when needed — a dedicated scan-validation deployment) rather than
  by splitting the codebase.

Extraction path: modules communicate through service interfaces and domain
events, never by reaching into each other's tables. Any module whose load profile
diverges enough (realistically: access control) can be lifted out later without
a rewrite.

## 4. Quality attributes, in priority order

1. **Tenant isolation.** A cross-tenant data leak is an existential failure for a
   B2B SaaS. Defence in depth: tenant context middleware, repository-level
   scoping, PostgreSQL Row Level Security, and an automated isolation test suite
   that runs on every commit. See [04](04-multitenancy.md).
2. **Financial correctness.** No lost, duplicated or silently mutated money.
   Integer minor units, append-only financial records, price snapshots,
   idempotent webhooks, explicit refunds. See [09](09-payments.md).
3. **Matchday availability.** The scanner must admit people even when the API is
   unreachable. See [ADR-0006](../decisions/ADR-0006-ticket-credentials.md).
4. **Privacy of minors and medical data.** The academy holds data on children.
   Medical data is special-category under GDPR Art. 9. Both get structural
   separation, not just permission checks. See [06](06-authorization.md).
5. **Operational efficiency of the admin UI.** Club staff are not power users but
   they use this daily. Information density and predictability beat visual
   novelty. See [14](14-design-system.md).
6. **Time-to-market for Phase 1.** Every deferral is recorded explicitly rather
   than discovered later.

## 5. Technology summary

| Layer | Choice | Notes |
| --- | --- | --- |
| Backend | Python 3.12+, FastAPI, Pydantic v2 | Async I/O throughout the API |
| ORM / migrations | SQLAlchemy 2.x (async, `Mapped[]` style), Alembic | |
| Database | PostgreSQL 17 | Shared DB, shared schema, RLS |
| Cache / locks / broker | Redis 7 | Not a source of truth, ever |
| Background work | Celery 5 + Redis, Celery Beat for schedules | Durability backed by outbox |
| Identity | Keycloak (OIDC) | Authentication only; authorization is ours |
| Object storage | S3-compatible; MinIO in dev | Signed URLs |
| Public web | Next.js 15 App Router | SSR/ISR, SEO, custom domains |
| Admin / super-admin / scanner | React 19 + Vite + TanStack Router | SPAs; no SSR benefit |
| Styling | Tailwind CSS v4 + Radix primitives + CVA | Shared token system |
| Observability | structlog JSON, OpenTelemetry, Sentry | Correlation IDs end to end |
| Reverse proxy | Caddy | On-demand TLS per club domain, guarded by an ask endpoint |
| Payments | Stripe (Billing + Connect) behind a provider port | Swappable |

## 6. Deployment shape

```
                    ┌── CDN / WAF ──┐
                    │               │
   club.com ────────┤  public-web   │ (Next.js, containerised, ISR via Redis)
   admin.footbola ──┤  admin-web    │ (static SPA)
   platform.… ──────┤  super-admin  │ (static SPA)
   scan.…  ─────────┤  scanner PWA  │ (static SPA + service worker)
                    └───────┬───────┘
                            │ HTTPS /api/v1
                    ┌───────▼────────────────────┐
                    │  FastAPI (N replicas)      │
                    │  Celery workers (M)        │
                    │  Celery beat (1)           │
                    └───┬──────────┬─────────┬───┘
                        │          │         │
              managed Postgres  managed   object storage
              (+ read replica)   Redis     (S3-compatible)
                        │
                    Keycloak (managed or containerised)
```

Containers are the deployment unit. Managed Postgres/Redis/object storage in
production — we do not run stateful services ourselves. No Kubernetes until a
measured need appears; container services (ECS / Azure Container Apps / Cloud Run
/ Hetzner + Nomad) are sufficient and cheaper to operate. See
[ADR-0010](../decisions/ADR-0010-deployment-topology.md).

## 7. What is explicitly out of scope for the initial architecture

Recorded so they are deliberate omissions rather than oversights:

- Microservices, service mesh, Kubernetes
- Kafka or any streaming platform (the outbox + Celery covers our needs)
- Elasticsearch / OpenSearch (Postgres FTS and trigram indexes suffice at our
  volumes; revisit when fan search exceeds ~5 M rows or fuzzy scouting search is
  built)
- GraphQL (REST + generated TS client gives us typed clients with less machinery)
- Database-per-tenant (architected for, not built — see [04](04-multitenancy.md))
- Native mobile apps (the scanner is a PWA; see the iOS caveat in
  [open questions](open-questions.md))
