# ADR-0002 — Shared database, shared schema, with Row Level Security

**Status:** Accepted · **Date:** 2026-08-13

## Context

300 tenants by year 3, ranging from a 40-player academy to a club with 20 000
supporters. A cross-tenant data leak would be existential for a B2B SaaS.

## Options

| | Shared schema | Schema per tenant | Database per tenant |
| --- | --- | --- | --- |
| Migrations | One | 300 runs, partial-failure states | 300 DBs |
| Connection pooling | Efficient | Degrades — `search_path` per session | Poor; 300 pools |
| Isolation strength | Logical (RLS) | Better | Strongest |
| Cross-tenant reporting | Trivial | Painful | Very painful |
| Per-tenant restore | Hard | Moderate | Trivial |
| Onboarding a tenant | Insert a row | DDL at runtime | Provision a database |
| Operational cost at 300 | Low | High | Very high |

Schema-per-tenant is the worst of both: it does not give the isolation guarantee
of a separate database, but it does give the migration and pooling pain.

## Decision

**Shared database, shared schema**, with `tenant_id` on every tenant-scoped
table and **four independent isolation layers**: request-scoped tenant context,
repository base-class filtering, PostgreSQL RLS with a non-`BYPASSRLS` runtime
role, and composite tenant foreign keys. Detail in
[04](../architecture/04-multitenancy.md).

Isolation is verified by a generated test suite that probes every route with
another tenant's object IDs, so coverage cannot fall behind new endpoints.

## Consequences

**Good.** One migration path. Efficient pooling. Trivial tenant onboarding.
Platform-wide analytics is a normal query. RLS means a missing `WHERE` clause
returns zero rows instead of leaking.

**Bad.** RLS costs 1–3 % on query time and defeats some optimisations on large
analytical queries (handled by running read-model jobs under an explicit
platform role). Per-tenant point-in-time restore requires row-level export rather
than a database restore — accepted, and the reason a tenant-export tool is built
in Phase 1 rather than when first needed.

**Operational rules, non-negotiable.** PgBouncer in transaction mode only; tenant
context set with `SET LOCAL`; asyncpg statement cache disabled; the application
role never holds `BYPASSRLS`.

**Escape hatch.** All data access resolves a connection through a
`TenantConnectionResolver` that today returns one shared engine. Moving an
enterprise tenant to a dedicated database changes only that resolver.
