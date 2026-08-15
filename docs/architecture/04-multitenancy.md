# 04 — Multitenancy Strategy

## 1. Model

**Shared database, shared schema, `tenant_id` on every tenant-scoped table**, with
PostgreSQL Row Level Security as an independent enforcement layer.

Hierarchy: `Tenant → Club → Team`. A tenant may hold many clubs; most will hold
one. Nothing in the code may assume `tenant.clubs.count == 1` — the admin UI
therefore always shows a club context switcher, hidden only when a tenant has
exactly one club (a presentation decision, never a data-model one).

## 2. Four independent isolation layers

Isolation must not depend on a developer remembering a `WHERE` clause. Four
layers, each of which alone would prevent a leak:

### Layer 1 — Request-scoped tenant context

Resolved by middleware, in this priority order:

1. **Host header** — for `public-web`, `club_domain.hostname` maps to club →
   tenant. Unknown host → 404, never a fallback tenant.
2. **JWT claim** — staff and fan tokens carry `tenant_id`.
3. **Explicit header** — `X-Tenant-Id`, accepted *only* from platform users with
   an active impersonation session or a support-read permission.

A submitted `tenant_id` in a body or query string is **never** trusted. If a
payload contains one, it is validated against the context and rejected with
`TENANT_MISMATCH` if different. This is a lint-enforced rule: Pydantic request
schemas may not declare a `tenant_id` field (a CI check greps for it).

The resolved context is stored in a `ContextVar`, propagated to async tasks and
Celery jobs, and attached to every log line and span.

### Layer 2 — Repository base class

All repositories extend `TenantScopedRepository`, which injects the tenant filter
into every query and stamps `tenant_id` on every insert. Constructing a raw
`select(Model)` for a tenant-scoped model outside a repository fails a CI check.

```python
class TenantScopedRepository[T: TenantScopedModel]:
    def _base(self) -> Select[tuple[T]]:
        return select(self.model).where(self.model.tenant_id == current_tenant_id())
```

### Layer 3 — PostgreSQL Row Level Security

The real backstop. Every tenant-scoped table:

```sql
ALTER TABLE player ENABLE ROW LEVEL SECURITY;
ALTER TABLE player FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON player
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
```

Key details:

- `current_setting(..., true)` returns NULL when unset, so `tenant_id = NULL` is
  never true → **no rows**. The failure mode is an empty result, not a leak.
- `FORCE ROW LEVEL SECURITY` so the table owner is also constrained.
- The application connects as `app_runtime`, a role **without** `BYPASSRLS` and
  without table ownership. Migrations run as `app_migrator`, which owns the
  schema and is used by nothing else.
- The variable is set per transaction:
  `SET LOCAL app.tenant_id = :tenant_id` — issued by a SQLAlchemy
  `after_begin` event listener. `SET LOCAL` is transaction-scoped, which is
  exactly what makes this safe behind a transaction-pooling connection pooler.

Platform/cross-tenant operations use a distinct role, `app_platform`, granted
`BYPASSRLS`, obtained only through an explicit
`async with platform_scope(reason=...)` context manager that writes an audit
record on entry. Reaching for that context manager is visible in review and in
the audit log.

### Layer 4 — Composite foreign keys

As described in [03 §0.1](03-data-model.md#01-why-composite-tenant-foreign-keys):
`FOREIGN KEY (tenant_id, team_id) REFERENCES team (tenant_id, id)`. Even with all
three layers above defeated, a row cannot be attached across tenants.

## 3. Connection pooling caveats (must not be discovered in production)

- **PgBouncer must run in transaction mode**, not session mode. `SET LOCAL` is
  transaction-scoped and therefore correct; a plain `SET` would leak tenant
  context between pooled clients. Any use of `SET` without `LOCAL` on the
  runtime connection is a CI-blocked pattern.
- **asyncpg + PgBouncer**: prepared statement caching must be disabled
  (`statement_cache_size=0`, `prepared_statement_cache_size=0` in the SQLAlchemy
  URL) or connection reuse produces "prepared statement already exists" errors
  under load. This bites during the first ticket on-sale, not during development.
- SQLAlchemy's own pool sits behind PgBouncer; sizing is
  `api_replicas × pool_size ≤ pgbouncer default_pool_size`.

## 4. RLS cost

RLS adds a predicate to every query. Since every tenant-scoped index is already
`tenant_id`-prefixed, the planner uses the same index either way; measured
overhead on comparable systems is 1–3 %. We accept that unconditionally — the
alternative is trusting application code with the company's survival.

One real cost: RLS defeats some partition-pruning and join-elimination
optimisations on very large analytical queries. Analytics read models are built
by jobs running under `app_platform` with explicit tenant filters, so the
reporting path is unaffected.

## 5. Tenant lifecycle

| State | Meaning | Behaviour |
| --- | --- | --- |
| `PENDING` | Created, onboarding incomplete | Admin login only, no public site |
| `ACTIVE` | Normal | All entitled features |
| `SUSPENDED` | Non-payment or policy | Admin read-only, public site shows a neutral maintenance page, **existing tickets still scan** |
| `CLOSED` | Terminated | No access; data retained for the contractual window, then purged |

Suspension deliberately does not break matchday. A club that has not paid us must
not be unable to admit spectators who have paid *them*; that would convert a
billing dispute into a public-safety incident and a lawsuit. Enforcement of
non-payment is commercial, not technical.

## 6. Path to dedicated databases (not built now)

Enterprise tenants may later require a dedicated database (data residency,
procurement requirements, noisy-neighbour SLAs). We keep that possible without
building it:

- All data access goes through a session factory that resolves a
  **connection by tenant** via a `TenantConnectionResolver`. Today it returns the
  single shared engine for every tenant. A dedicated-DB deployment changes only
  that resolver.
- No query joins across tenants except in `analytics` read models, which are
  built per tenant and would simply run per database.
- Tenant-scoped IDs are UUIDs, so migrating a tenant to its own database is a
  copy, not a re-keying exercise.
- Global tables (`plan`, `feature`, `permission`, `user_account`) are already
  distinguishable from tenant tables by their base class, so we know exactly what
  a dedicated database would need to replicate.

Trigger to actually do it: a signed enterprise contract requiring it, or a single
tenant exceeding ~20 % of total database load.

## 7. Isolation test suite (mandatory, runs on every commit)

`backend/tests/isolation/` contains generated tests, not hand-written ones:

1. **Model sweep.** Enumerate every SQLAlchemy model. Assert each one either
   inherits `TenantScopedModel` or is on an explicit `GLOBAL_MODELS` allow-list.
   A new tenant-scoped table without `tenant_id` fails CI immediately.
2. **RLS sweep.** For every tenant-scoped table, assert RLS is enabled *and*
   forced, and that a policy exists. Compares against the live schema, so a
   migration that creates a table without RLS fails.
3. **Cross-tenant probe.** Seed two tenants with identical-shaped data. For every
   registered API route, call it authenticated as tenant A with tenant B's object
   IDs. Assert 404 (not 403 — a 403 confirms the object exists). Any 200 is a
   test failure.
4. **Context-leak probe.** Run concurrent requests for different tenants against
   the same worker and assert no bleed via `ContextVar` or connection reuse.
5. **Raw-SQL audit.** Static check that every `text()` / raw SQL string in domain
   modules is on a reviewed allow-list.

Test 3 is the one that catches real bugs. It is generated from the route table,
so a new endpoint is covered the day it is written, without anyone remembering.
