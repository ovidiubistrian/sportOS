# 15 — Testing Strategy

## 1. Shape

```
        ╱  E2E (Playwright)          ~40 specs — the journeys that make money
      ╱    API / integration          ~500 — real Postgres, real transactions
    ╱      Service / unit             ~1500 — domain logic, no I/O
  ╱        Contract & invariant       generated — isolation, permissions, schema
```

The bottom band is unusual and the most valuable part: tests that are *generated
from the system* rather than written per feature. They cannot be forgotten when
someone adds an endpoint in a hurry, which is exactly when they are needed.

## 2. Backend

**Unit** — pure domain logic with no database: fee calculation, money arithmetic
and rounding, permission resolution, ticket state machine transitions, seat
allocation rules, loyalty expiry, evaluation scoring, ICU-independent date logic.
Fast (< 10 s for the whole suite), no fixtures, no mocks of our own code.

**Repository integration** — real PostgreSQL (Testcontainers), one transaction per
test rolled back afterwards. Tests constraints and indexes, not just Python:
composite FKs, partial unique indexes, exclusion constraints, RLS policies.

> We do not use SQLite for tests. It does not have RLS, partial indexes on
> expressions, exclusion constraints, `CITEXT`, or the same transaction
> semantics — meaning the things most likely to break would be exactly the
> things untested.

**Service tests** — business flows against a real database with fake adapters for
external systems (`MockPaymentProvider`, `MockStoragePort`, `MockEmailSender`).

**API tests** — through the ASGI app with real auth tokens, asserting status
codes, error codes, pagination envelopes and permission behaviour.

### Mandatory suites

| Suite | What it asserts | Failure means |
| --- | --- | --- |
| **Tenant isolation** | See [04 §7](04-multitenancy.md) — model sweep, RLS sweep, cross-tenant probe over every route, context-leak probe | Ship-blocking |
| **Permission matrix** | Every route × every role template against a checked-in expectation matrix; a route with no entry fails | Ship-blocking |
| **Entitlement gating** | Every gated route returns 402 when the feature is off | Ship-blocking |
| **Ticket concurrency** | See §3 | Ship-blocking |
| **Payment webhooks** | Duplicate delivery, out-of-order delivery, replay, signature failure, unknown event | Ship-blocking |
| **Money invariants** | Property-based: fee splits sum to the whole; refunds never exceed captured; no float ever appears; zero- and three-decimal currencies | Ship-blocking |
| **Migration** | Every migration applies to an empty DB *and* to a snapshot of production schema; downgrades run where declared reversible | Ship-blocking |
| **Audit coverage** | Every `is_sensitive` permission produces an audit row | Ship-blocking |
| **Medical isolation** | A non-medical connection gets a database-level permission error on every `medical.*` table | Ship-blocking |
| **PII leak** | Log output and event payloads scanned for email/phone/name patterns | Ship-blocking |

## 3. Concurrency tests — explicitly required

These use real concurrent connections against real Postgres. Not mocked, not
simulated with `asyncio.gather` on a single connection.

```python
async def test_no_overselling_on_last_seat():
    event = await seeded_event(seats=1)
    results = await asyncio.gather(*[
        purchase_in_own_connection(event, seat) for _ in range(50)
    ], return_exceptions=True)

    assert sum(1 for r in results if not isinstance(r, Exception)) == 1
    assert all(isinstance(r, SeatUnavailable)
               for r in results if isinstance(r, Exception))
    assert await count_tickets(event) == 1
```

Covered scenarios:

| Scenario | Invariant |
| --- | --- |
| 50 buyers, 1 seat | Exactly 1 ticket, 49 clean `SeatUnavailable` |
| 200 buyers, 100 GA tickets | Exactly 100 sold, `quantity_sold + held ≤ total` always |
| Concurrent hold expiry + purchase | No double-allocation; expired hold is reusable |
| 10 devices scanning one credential simultaneously | Exactly 1 `VALID`, 9 `ALREADY_USED` |
| Offline scans from 2 disconnected devices, same credential | Both admitted offline (accepted, documented); exactly 1 `VALID` after sync, the second flagged for reconciliation |
| Concurrent refund + transfer on one ticket | One succeeds, state machine stays valid |
| Concurrent loyalty redemptions | Balance never goes negative |
| Concurrent stock reservation | `reserved ≤ on_hand` always |

Each runs 20 iterations in CI to catch scheduling-dependent races.

## 4. Frontend

**Component tests** (Vitest + Testing Library) — behaviour, not implementation.
Queried by role and label, so a test that passes proves the component is
accessible. `axe-core` assertion in every pattern test.

**Design system** — Storybook with all five states per component; Playwright
visual regression over the Storybook index.

**Critical workflow tests** — MSW-backed integration tests for checkout, seat
selection, scanning, academy registration and the permission-driven navigation.

## 5. E2E (Playwright)

Against the full Docker Compose stack with the demo seed and Stripe test mode.

Required journeys:

1. Fan registers → verifies email → completes profile
2. Fan buys 2 GA tickets → 3DS challenge → receives credentials → sees them in the account
3. Fan buys an assigned seat → seat map → hold → pay → ticket issued
4. Steward scans a valid ticket → VALID; rescans → ALREADY_USED with prior scan detail
5. Steward scans offline → queued → reconnects → syncs → server agrees
6. Fan buys a membership → discount applies to a subsequent ticket purchase
7. Shop checkout with variants, a discount code and a member discount
8. Academy registration by a guardian, with consent capture for a minor
9. Coach records attendance for a session; parent sees it in the portal
10. Coach cannot open another team's players (403/404 path)
11. Club admin publishes an article → appears on the public site in the right locale
12. Refund a ticket → credential revoked → scan returns REVOKED → platform fee reversed
13. Super admin changes a tenant's plan → gated feature disappears in admin-web
14. Support impersonation → banner visible → audit row written → tenant owner emailed
15. Ticket transfer: owner initiates → recipient accepts → old credential dead, new one works

Journeys 4, 5, 12 and 15 are the ones that fail silently in a way users notice at
the worst possible moment, so they run on every merge to main, not nightly.

## 6. Fixtures

**Builders, not JSON fixture files.** Fixture files rot, get copy-pasted, and
encode assumptions nobody remembers.

```python
club = ClubBuilder().with_academy(teams=6).build()
player = PlayerBuilder().in_team(club.u15).aged(14).with_guardian().build()
event = TicketedEventBuilder().at(club.venue).with_seated_section(rows=20, seats=25).build()
```

Rules: realistic names in the target locales (including diacritics — `Ștefănescu`
catches encoding and sort bugs that `Test User 1` never will), realistic volumes
in performance tests, and every builder produces a valid aggregate by default so
tests state only what they care about.

## 7. Performance tests

Run pre-release against a staging environment seeded to pilot volumes:

| Scenario | Target |
| --- | --- |
| Ticket on-sale: 5 000 users in 60 s | p95 checkout < 2 s, zero oversell, zero 500s |
| Scan validation: 40/s for 15 min | p99 < 150 ms |
| Supporter list, 50 000 rows, filtered | p95 < 400 ms |
| Public homepage under CDN miss | p95 < 800 ms |
| Nightly analytics aggregation | < 10 min for the largest tenant |

## 8. CI pipeline

```
PR:     lint · typecheck · unit · repository · API · isolation · permissions ·
        entitlements · concurrency · frontend component · build all apps ·
        OpenAPI diff · bundle budgets            (target < 8 min)

main:   the above + full E2E + visual regression + migration-against-prod-schema

nightly: performance · dependency audit · container scan · Lighthouse ·
         accessibility sweep · demo-seed rebuild
```

Coverage is measured but **not gated on a global percentage** — a number that
mostly incentivises testing getters. Gated instead on: no untested file in
`payments`, `ticketing`, `access_control`, `billing`, `privacy` or `medical`, and
no route missing a permission-matrix entry. Those are the places where a gap
actually costs something.
