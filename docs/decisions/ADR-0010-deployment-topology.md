# ADR-0010 — Containers on managed infrastructure, no Kubernetes

**Status:** Accepted · **Date:** 2026-08-13

## Context

Production must be reliable enough for matchday, cloud-agnostic enough for
European procurement (some clubs and municipalities require EU data residency and
specific providers), and operable by a team with no dedicated SRE.

## Decision

**Containerised applications on a managed container service, with managed
Postgres, Redis and object storage.**

```
CDN + WAF
   └── container service
        ├── api          (N replicas, autoscaled)
        ├── public-web   (N replicas, Redis-backed ISR cache)
        ├── worker       (M replicas)
        ├── beat         (exactly 1)
        └── outbox-relay (2+)
   ├── managed PostgreSQL (+ read replica, PITR, automated backups)
   ├── managed Redis (persistence enabled)
   ├── object storage (S3-compatible) + CDN
   └── Keycloak (managed, or containerised with a managed database)
```

Static frontends (`admin-web`, `super-admin`, `scanner`) are built assets on the
CDN, not containers.

Target platforms, in order of preference for the first deployment: Azure
Container Apps, AWS ECS Fargate, Google Cloud Run, or Hetzner/OVH with Nomad for
cost-sensitive European deployments. The application does not know which.

**No Kubernetes** until a measured need appears.

## Rationale

**Why managed data services.** Running Postgres ourselves means owning backups,
PITR, failover, version upgrades and disk management. That is a full-time role we
do not have, and the failure mode is losing a club's data.

**Why not Kubernetes.** It solves problems we do not have — multi-team cluster
sharing, complex service topologies, sophisticated scheduling. It costs a control
plane to operate, a large surface to secure, and an expertise dependency in a
small team. Five container definitions do not need it.

**Why cloud-agnostic.** European clubs and municipalities have procurement
constraints. Our coupling points are limited to: an S3-compatible API, a
Postgres connection, a Redis connection and an OTLP endpoint. All four are
portable.

## Consequences

**Good.** Small operational surface. Managed backups and failover. Portable
between providers in days, not months. Cost scales with usage.

**Bad.**
- Managed services cost more per unit than self-hosted. Correct trade against an
  SRE salary and the risk of data loss.
- Container platforms differ in autoscaling, secrets and networking — some
  per-platform deployment configuration is unavoidable. Kept in
  `infrastructure/environments/`, out of application code.
- No Kubernetes means no off-the-shelf operators. Not currently needed.

**Operational rules.**
- **Migrations run as an explicit, gated pipeline step**, never on container
  start. N replicas racing `alembic upgrade head` on deploy is a real outage, and
  it removes the rollback point.
- Every deploy is a new immutable image tag; rollback is redeploying the previous
  tag.
- `beat` runs as exactly one instance — duplicated scheduled jobs would double
  notifications and corrupt aggregates.
- Secrets come from a secret manager at runtime. Never baked into images, never
  in environment files in the repository.
- Zero-downtime deploys require backward-compatible migrations: expand, deploy,
  migrate data, contract in a later release. Destructive schema changes never
  ship in the same release as the code that stops using the column.

**Revisit if.** We run more than ~15 distinct services, need multi-region active-
active, or hire dedicated platform engineers.
