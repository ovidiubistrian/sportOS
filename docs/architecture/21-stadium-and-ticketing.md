# 21 — Stadium and ticketing

## The rule everything else follows from

> **The live venue configuration is never match inventory.**

Creating a match serialises the whole stadium layout into an
`EventConfigurationSnapshot` and mints one `EventSeatInventory` row per
admission. From that moment the match reads the master for nothing at all —
not to draw its map, not to price a seat, not to decide which gate a ticket
opens.

This is enforced structurally rather than by discipline: there is no code path
from a `ticketed_event` to a `stand`, `section` or `seat` row. Redrawing the
ground in March cannot move somebody who bought in January, because there is
nothing to move them through.

The second half of the rule is that a published configuration is immutable.
`venue_service.assert_editable` refuses every write beneath it; editing forks a
new draft at the next version, and the seats in the copy are **new rows**, so a
match snapshotted from version 3 keeps pointing at seats no later edit reaches.

## Shape

```
venue ─── venue_configuration ─┬─ stand ─── section ─── seat_row ─── seat
    (master, versioned)        ├─ gate ─── gate_section ──┘
                               ├─ access_zone
                               └─ price_zone
                    │
                    │  snapshot taken once, at match creation
                    ▼
ticketed_event ─┬─ event_configuration_snapshot   (the frozen drawing)
                ├─ event_seat_inventory           (one row per admission)
                ├─ allocation                     (hard holds, soft allocations)
                └─ event_entitlement ─── ticket ─── access_credential
                                                          │
                                              scan_log ───┘
```

Every table is tenant-scoped with forced RLS, and every child points at its
parent through a **composite** foreign key carrying `tenant_id` — so a
cross-tenant reference is not merely denied, it is unrepresentable.

## Naming, and why it differs from the brief

| Brief | Here | Why |
| --- | --- | --- |
| `MatchEvent` | `TicketedEvent` | `MatchEvent` already means a goal or a card in `app/competitions`. `Match` there is *global* reference data — one fixture shared by both clubs — whereas a ticketed event belongs to the club selling. |
| `Customer` | reused | `Order` carries buyer name, email and phone; `fans` carries supporter accounts. A third identity would need reconciling with both. |
| `Cart`, `Order`, `OrderItem`, `Payment` | reused | `LINE_TYPES` already contained `TICKET` and `SEASON_TICKET`; the ordering kernel (ADR-0005) takes a handler per line type. A mixed basket — two tickets, a scarf, one payment — works by construction. |

## How double-selling is prevented

Not in the browser, and not in the service's memory.

1. **One row per admission**, under `UNIQUE (event_id, seat_id)`. Two sold rows
   for the same seat cannot exist.
2. **Every transition takes `SELECT ... FOR UPDATE`, ordered by primary key.**
   Two baskets racing for the last seat serialise: the first sets `CART_HELD`
   and commits, the second wakes on the lock, re-reads, sees a live hold and is
   refused with `SeatUnavailable`. The ordering matters as much as the lock —
   `{A,B}` against `{B,A}` without it deadlocks under load.
3. **One entitlement per inventory row**, under `UNIQUE (inventory_id)`. Even a
   broken state machine could not give the same admission to two people.

Holds expire on their own. `hold_expires_at` is checked by every read *and*
write path, so a seat comes back whether or not the sweep in
`ticketing/maintenance.py` has run. The sweep exists to keep reports honest,
not to keep the system correct — a sweep that correctness depends on takes the
system down with it when it stops.

## Access control

Single admission is a database constraint (ADR-0006):

```sql
UNIQUE (credential_id) WHERE result = 'VALID' AND scan_type = 'ENTRY'
```

A second scan attempts an insert, violates the index, and the violation *is*
the answer — converted to `ALREADY_USED` and itself recorded as a separate row.
Correct across replicas, because there is no read to race with the write.

The QR carries an opaque 160-bit reference and an Ed25519 signature over
`(reference, event, section, gates, validity window, key_id)`. **No personal
data**: a ticket photographed and posted online reveals nothing about its
holder. `key_id` travels with the credential so keys rotate without
invalidating what is already issued.

Signature verification proves a code is not forged. It does **not** prove the
ticket is unused — that is the constraint above, and no amount of cryptography
substitutes for it.

### The offline limit, stated plainly

**Two fully disconnected devices cannot detect a duplicate between themselves.**
The constraint lives in a database neither can reach. This is arithmetic, not a
gap to be closed later.

Mitigations, none of which eliminate it:

- **Gate-partitioned manifests** — a credential valid only at Gate B is absent
  from Gate D's manifest, which shrinks the exposure to near zero for seated
  tickets. General admission at a shared gate stays exposed for the outage.
- **Frequent synchronisation** — the window is the outage, so shorten it.
- **A local stadium controller** — one authority inside the ground when the WAN
  is gone, which trades the problem for an availability one.
- **Post-match reconciliation** flags every duplicate with gate, device and
  operator.

Offline mode must be an explicit, audited operator action behind a persistent
banner, never a silent fallback: a steward must always know which guarantee
they are working under. See [Q5](open-questions.md#q5) — the residual risk is
accepted by the club in writing.

## Season tickets

A season pass is **not** one ticket that works twenty times. It mints a separate
`EventEntitlement` — and a separate ticket and QR — for every included match, on
the same physical seat.

That is what makes releasing match fourteen back to the club, transferring one
game, or cancelling a single fixture possible without touching the other
nineteen. Modelled as one unlimited credential, every one of those operations
would need a per-match exception table invented later.

## Pricing

A matrix of **price zone × ticket type**, in a `PriceList` that applies at one of
three levels, resolved narrowest-first:

```
EVENT  →  SEASON  →  VENUE
```

A club sets the ground's prices once, adjusts for a season, overrides a derby —
without restating the rows it did not change.

Refusing to price is correct behaviour. A club that has not priced the away end
has not decided what the away end costs, and falling back to zero would sell
tickets at a price nobody approved. `publish_event` refuses a match with a
sellable zone that has no price.

VAT is a rate in basis points plus an `is_included` flag, never a precomputed
net and gross — clubs disagree about which number is "the price", and storing
only the derived pair loses the answer.

## Roles

| Role | Holds |
| --- | --- |
| Ticketing Manager | The whole operation: stadium, matches, prices, allocations, season tickets, reports |
| Box Office | Orders, customer lookup, issue and reprint. **Not** pricing, **not** the stadium |
| Gate Operator | `ticketing.access.scan` and `ticketing.event.read`, and nothing else |
| Ticketing Analyst | Reports. Nothing that writes |

The gate operator's two permissions are deliberate. A steward's handset is lost,
borrowed and left on walls; whatever it reaches is what whoever picks it up
reaches.

## Known limitations

- **General admission is one row per place.** Uniform with reserved seating and
  individually blockable, at the cost of storage. Fine to the ~200,000-row
  ceiling in `event_service.MAX_INVENTORY_ROWS`; a 60,000-capacity terrace-heavy
  ground would want a counter-backed pool instead.
- **Re-entry is expressible but not honoured.** `AccessRule.allow_reentry`
  exists; the single-admission index covers ENTRY scans, so a second entry is
  refused. Supporting it properly needs an exit-before-entry model.
- **Not implemented in this slice:** CSV seat import/export, undo/redo in the
  editor, PDF ticket rendering, payment in instalments, official resale,
  flexible match packages, and the public seat-selection page (the API it needs
  is complete and exercised; the buyer-facing screen is not built).
- **Dynamic pricing is deliberately absent**, as specified.
