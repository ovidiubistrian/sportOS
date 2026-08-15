# ADR-0003 — Keycloak for authentication, application-owned authorization

**Status:** Accepted · **Date:** 2026-08-13

## Context

We need email/password, Google and Apple login, MFA (mandatory for platform and
finance roles), secure session handling, brute-force protection and account
recovery — across staff, fans, guardians and stewards.

We also need scoped RBAC: a coach at U15 in one club, a scout at another, with
permissions that change immediately when an academy director revokes them.

## Decision

**Keycloak, one realm (`football-os`) for all tenants and populations.**
Authentication only. The business permission model stays in our database.

Tokens carry identity, tenant membership and authentication strength (`amr`,
`acr`). They carry **no** club/team scopes and **no** permission keys.

## Rationale

**Why not build authentication ourselves.** Password reset, MFA enrolment,
social login, session revocation, brute-force protection and token issuance are
each individually easy to get subtly wrong, and collectively months of work with
permanent security liability.

**Why one realm.** Realm-per-tenant means 300 sets of clients, mappers and
identity providers, linear cache cost, and no shared fan identity. Realm-per-
population means the coach who is also a season-ticket holder has two identities.

**Why permissions stay ours.** Three reasons, any one sufficient:
1. A user with roles across several teams and clubs would produce tokens too
   large for practical HTTP headers.
2. Permission revocation must be immediate, not at next token refresh.
3. Every role change would become a write to Keycloak's admin API — a hot path
   through a system we do not control, coupling our uptime to theirs.

## Consequences

**Good.** MFA, social login and session security are configuration. Our
authorization model is a normal, testable part of the codebase. Permission checks
are a Redis lookup, not a network call.

**Bad.**
- Another stateful service to run, upgrade and monitor. Mitigated by using a
  managed Keycloak or a well-understood container deployment with a managed
  database.
- Two sources of user state (Keycloak + `user_account`), requiring JIT creation
  and nightly reconciliation.
- The hosted login page conflicts with white-label domains — see
  [Q2](../architecture/open-questions.md#q2). Themed login in Phase 1, per-tenant
  auth CNAMEs in Phase 2.
- ~2.5 M fan users in one realm by year 3 needs planning; our admin UI never
  proxies Keycloak user search, and backups are database-level.

**Reversibility.** Moderate. OIDC is standard and `user_account.subject_id` is
the only coupling, but migrating credentials between IdPs is a real project.
