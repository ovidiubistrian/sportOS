# ADR-0001 — Modular monolith over microservices

**Status:** Accepted · **Date:** 2026-08-13

## Context

Football Club OS spans ~30 domains. The team is 4 engineers. Peak load is ~200
orders/sec during a ticket on-sale and ~40 scans/sec on matchday, against a
year-3 target of 300 tenants.

The domains are not independent. A single ticket purchase touches inventory,
ordering, payments, credentials, loyalty, notifications and the platform fee
ledger, and must be atomic where money and inventory are concerned.

## Options

**A. Microservices.** Independent scaling and deployment. Costs: a saga for every
purchase with compensating actions, distributed tracing as a prerequisite rather
than a nicety, N deployment pipelines, and eventual consistency in a domain where
overselling a seat is a business failure.

**B. Single-package monolith.** Fastest to start. Degrades predictably: within a
year, `services/` holds 200 files, everything imports everything, and extraction
is impossible.

**C. Modular monolith with enforced boundaries.** One deployable, vertical domain
modules, dependency rules enforced in CI.

## Decision

**Option C.** One FastAPI deployable plus a worker deployable running the same
image. Modules communicate through service interfaces and domain events, never by
importing each other's models or repositories. Enforced by `import-linter`
contracts in CI (see [02](../architecture/02-domain-boundaries.md)).

## Consequences

**Good.** A ticket purchase is one database transaction plus an outbox row —
correct by construction rather than by saga. One deployment, one log stream, one
trace. Refactoring across boundaries is a compile-time-checked operation.

**Bad.** All modules scale together; a memory leak anywhere affects everything;
deploys are coupled. Mitigated by running the same image in differently-sized
deployments and by keeping the deploy pipeline fast enough that coupling does not
hurt.

**Extraction trigger.** A module whose load profile diverges sharply — realistically
only `access_control`. Because it depends on nothing but credential validation
and an append-only scan log, extraction is a deployment change, not a rewrite.
