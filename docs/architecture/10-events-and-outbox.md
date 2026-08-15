# 10 — Domain Events & Transactional Outbox

## 1. Why events at all in a monolith

Not for decoupling fashion. For three concrete reasons:

1. **A ticket purchase must trigger six unrelated things** — credential minting,
   confirmation email, loyalty points, analytics, platform fee ledger, wallet
   pass. Wiring six direct calls into the purchase service makes it own all six
   failure modes and turns a 200 ms checkout into a 4 s one.
2. **Side effects must not fail the transaction.** A bounced email must not
   un-sell a ticket.
3. **Boundaries.** `loyalty` reacting to `OrderPaid` means `commerce` does not
   import `loyalty`.

What we deliberately do **not** do: event sourcing. State lives in normal tables.
Events are notifications about state that has already been committed.

## 2. The lost-side-effect problem

The naive version is broken:

```python
await session.commit()        # ticket sold ✓
await celery_task.delay(...)  # process dies here → confirmation email never sent
```

or worse:

```python
await celery_task.delay(...)  # task starts, reads the row...
await session.commit()        # ...that does not exist yet → task fails
```

Both are real, both appear only under load, and both lose money or trust.

## 3. Transactional outbox

The event is written **in the same transaction as the state change**:

```python
async with uow() as tx:
    ticket = await self.repo.issue(ticket_data)
    tx.publish(TicketIssued(ticket_id=ticket.id, event_id=…, holder_id=…))
    # both the ticket row and the outbox row commit atomically, or neither does
```

A relay process polls and dispatches:

```sql
UPDATE outbox_event SET status = 'PUBLISHING', attempts = attempts + 1
WHERE id IN (
    SELECT id FROM outbox_event
    WHERE status = 'PENDING' AND available_at <= now()
    ORDER BY id
    LIMIT 100
    FOR UPDATE SKIP LOCKED          -- multiple relays, no contention, no duplication
)
RETURNING *;
```

`FOR UPDATE SKIP LOCKED` is what lets us run several relay workers safely.
Latency is a 200 ms poll interval, with `LISTEN/NOTIFY` as a low-latency nudge so
the common case is near-instant. Delivery is **at-least-once**; consumers must be
idempotent.

## 4. Consumer idempotency

Every handler records what it has processed:

```python
@handles(OrderPaid)
async def award_loyalty_points(event: OrderPaid, ctx: EventContext) -> None:
    async with uow() as tx:
        if not await tx.claim(handler="award_loyalty_points", event_id=event.id):
            return                                   # already done
        await loyalty.credit(
            person_id=event.person_id,
            points=…,
            idempotency_key=f"order:{event.order_id}",  # second line of defence
        )
```

`claim()` inserts into `processed_event (handler_name, event_id)`; the primary
key makes a duplicate a no-op. The claim and the effect commit together, so a
crash between them cannot mark work done that never happened.

## 5. In-process vs queued handlers

Two dispatch modes, chosen per handler:

| Mode | Use for | Guarantee |
| --- | --- | --- |
| **Synchronous, same transaction** | Invariants that must hold with the write: audit records, denormalised counters | Atomic |
| **Asynchronous via outbox → Celery** | Everything with an external side effect: email, SMS, wallet passes, analytics, third-party calls | At-least-once, eventually |

The test for which one: *if this fails, must the original operation be undone?*
Almost always no — which is why almost everything is asynchronous.

## 6. Event catalogue (initial)

```
Identity     UserRegistered · UserLinkedToPerson · RoleAssigned · RoleRevoked
Tenancy      TenantCreated · TenantSuspended · TenantReactivated · SubscriptionChanged
Academy      PlayerRegistered · PlayerTransferred · PlayerDeparted
             GuardianLinked · ConsentGranted · ConsentWithdrawn
Training     TrainingSessionScheduled · TrainingSessionCompleted · AttendanceRecorded
Development  EvaluationSubmitted · EvaluationShared · DevelopmentGoalAchieved
Medical      PlayerAvailabilityChanged            (never carries clinical detail)
Matches      FixtureScheduled · FixtureRescheduled · FixtureCancelled · MatchFinished
Ordering     CartCheckedOut · OrderCreated · OrderPaid · OrderFailed
             OrderCancelled · OrderRefunded
Ticketing    TicketIssued · TicketTransferred · TicketRevoked · TicketRefunded
Access       CredentialIssued · CredentialRevoked · TicketScanned · OfflineScansSynced
Membership   MembershipCreated · MembershipRenewed · MembershipExpired · MembershipCancelled
Commerce     StockReserved · StockReleased · OrderFulfilled · ShipmentDispatched
Fundraising  DonationCompleted · CampaignGoalReached
Payments     PaymentCaptured · PaymentFailed · RefundCompleted · PayoutPaid
             ConnectedAccountUpdated
CMS          ContentPublished · ContentScheduled · ContentArchived
Privacy      DataExportRequested · ErasureRequested · ErasureCompleted
Ops          DocumentExpiring · QualificationExpiring · InventoryHoldExpired
```

### Event contract

```python
@dataclass(frozen=True)
class DomainEvent:
    id: UUID                  # UUIDv7
    event_type: str           # "ticketing.ticket_issued"
    event_version: int        # schema version, bumped on breaking change
    tenant_id: UUID | None
    aggregate_type: str
    aggregate_id: UUID
    occurred_at: datetime
    correlation_id: str       # the originating request
    causation_id: UUID | None # the event that caused this one
    payload: Mapping[str, Any]
```

Payload rules:

- **IDs and immutable facts only.** No mutable entity snapshots — by the time a
  handler runs, the entity may have changed, and a stale copy in an event is a
  bug generator.
- **Never any PII beyond an ID.** No names, emails, addresses, and absolutely no
  medical or payment detail. Events are persisted, retried, and logged; treating
  them as PII-free keeps GDPR erasure from having to rewrite event history.
  A handler that needs the fan's email fetches it, checks consent at send time,
  and gets current data.
- Additive changes only within a version. Breaking changes bump
  `event_version`, and both versions are handled during the transition.

## 7. Failure handling

| Attempt | Backoff |
| --- | --- |
| 1–5 | 1 s, 5 s, 30 s, 2 min, 10 min |
| 6+ | `DEAD` — alert raised, visible and replayable in super-admin |

Dead events are never silently dropped. The super-admin UI lists them by tenant
and type with a replay action, because the alternative — a support engineer
writing ad-hoc SQL against production — is how data gets corrupted.

Published rows are deleted after 7 days by a scheduled job; `processed_event` is
pruned after 30 days. Both are partitioned to keep deletion cheap.

## 8. Ordering

Events are ordered per aggregate by `outbox_event.id` (UUIDv7 sorts by time), and
the relay claims in `id` order. There is no global ordering guarantee across
aggregates, and no handler may depend on one.

Where sequence genuinely matters (e.g. `OrderPaid` must precede `TicketIssued`),
it is expressed as **causation**: `TicketIssued` is emitted *by the handler of*
`OrderPaid`, not emitted independently and hoped to arrive second.

## 9. Why not Kafka / RabbitMQ / NATS

At our volumes (peak ~200 events/sec, typical < 5/sec), Postgres plus Redis is
comfortably sufficient and adds no new operational surface. A broker would add a
component to run, monitor, secure, upgrade and reason about during an incident —
and it would still need an outbox, because the atomicity problem is between the
database and the broker, not inside the broker.

Revisit if we exceed ~5 000 events/sec sustained, need cross-service fan-out to
systems we do not own, or need event replay windows measured in months.
