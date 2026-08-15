# ADR-0008 — Transactional outbox over a message broker

**Status:** Accepted · **Date:** 2026-08-13

## Context

A ticket purchase must trigger credential minting, a confirmation email, loyalty
points, analytics, the platform fee ledger and (later) a wallet pass. None of
those may fail the purchase; none of them may be silently lost.

The naive approach is broken in both directions: enqueueing before commit gives
tasks a row that does not exist yet; enqueueing after commit loses the side
effect if the process dies in between.

Volume: peak ~200 events/sec, typical under 5/sec.

## Decision

Events are written to an `outbox_event` table **in the same transaction as the
state change**. A relay process claims batches with
`FOR UPDATE SKIP LOCKED` and dispatches them to Celery. Consumers record
`processed_event (handler_name, event_id)` to make at-least-once delivery safe.

No Kafka, RabbitMQ or NATS.

## Rationale

**Why an outbox at all.** It is the only pattern that makes "state changed" and
"event emitted" atomic without a distributed transaction. Adding a broker does
not remove this need — the atomicity problem is *between the database and the
broker*, so we would need the outbox anyway.

**Why not a broker.** At 200 events/sec peak, Postgres plus Redis is comfortably
sufficient. A broker would add a component to run, secure, monitor, upgrade and
reason about during an incident, with no capability we currently need.

**Why `FOR UPDATE SKIP LOCKED`.** Lets several relay workers claim disjoint
batches without contention or duplication — the well-trodden Postgres queue
pattern, and the reason a dedicated broker is unnecessary at this scale.

## Consequences

**Good.** No lost side effects, ever. One system to operate. Events are queryable
with SQL, which makes incident investigation ordinary work. Replay is a status
update. Dead events are visible and replayable from super-admin rather than
requiring ad-hoc production SQL.

**Bad.**
- Polling latency (200 ms, reduced by `LISTEN/NOTIFY`). Irrelevant for emails,
  and nothing user-facing waits on an event.
- The outbox table is a write hotspot; mitigated by deleting published rows after
  7 days and partitioning.
- Every consumer must be idempotent. Enforced by a `claim()` helper that is the
  only sanctioned way to write a handler, plus a test that asserts each handler
  is safe under duplicate delivery.
- No global ordering across aggregates. Where sequence matters it is expressed as
  causation — the dependent event is emitted *by the handler of* the first, not
  emitted independently and hoped to arrive second.

**Revisit if.** Sustained load exceeds ~5 000 events/sec, we need fan-out to
systems we do not own, or we need replay windows measured in months.
