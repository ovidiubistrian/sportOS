# 02 — Domain Boundaries

A modular monolith only stays modular if the boundaries are mechanically
enforced. Convention alone degrades within months. This document defines the
layers, the allowed dependency directions, and the CI contracts that enforce
them.

## 1. Layered module tiers

Modules sit in tiers. **A module may only depend on modules in a lower tier**
(plus `core`). Same-tier dependencies are forbidden except where explicitly
listed as an allowed pair.

```
Tier 0  core                       config, db, errors, money, ids, clock, telemetry,
                                   pagination, tenant context, storage/port abstractions
                                   → imports nothing from tiers 1-5

Tier 1  Foundation                 tenants · identity · people · audit · media · privacy
                                   → the "who and where" of everything

Tier 2  Organisation               clubs · teams · staff · venues · competitions
                                   → depends on tier 1

Tier 3  Domain operations
        Sporting:                  players · guardians · academy · training ·
                                   development · medical · matches · scouting
        Commercial:                fans · memberships · loyalty · ticketing ·
                                   commerce · fundraising · sponsorship · cms · ai
                                   → depends on tiers 1–2. Sporting and Commercial
                                     do not import each other.
                                   `ai` is a support module for `cms`: it holds the
                                   provider port, the prompts and the usage meter,
                                   and it never reaches beyond one tenant. Anything
                                   cross-tenant (the super-admin console, the cost
                                   report) lives in `platform`.

Tier 4  Transaction & delivery     payments · access_control · notifications ·
                                   integrations
                                   → may be depended upon by tier 3, and may depend
                                     on tiers 1–2 only. See §3.

Tier 5  Platform & read-side       billing · platform · analytics
                                   → may read across everything; nothing depends on them
```

Two rules do most of the work:

1. **Nothing depends on tier 5.** Analytics and billing observe the system; the
   system never asks them for permission or data.
2. **Tier 4 never imports tier 3.** Payments does not know what a ticket is. This
   is what keeps Stripe out of the ticketing domain.

## 2. Dependency directions that matter

| Relationship | Direction | Mechanism |
| --- | --- | --- |
| `ticketing` → `payments` | ticketing asks payments to take money | Service call through `PaymentPort` |
| `payments` → `ticketing` | payment succeeded → issue tickets | **Domain event only** (`PaymentCaptured`) |
| `ticketing` → `access_control` | ticket issued → mint credential | Domain event (`TicketIssued`) |
| `access_control` → `ticketing` | scan validated → mark used | Service call (`ticketing.mark_admitted`) |
| `commerce`/`ticketing`/`fundraising` → `loyalty` | earn points | Domain event; loyalty subscribes |
| `medical` → `players` | availability status | `medical` publishes `PlayerAvailabilityChanged`; players/training read a projection |
| anything → `audit` | record sensitive action | Service call, in the same transaction |
| anything → `notifications` | tell someone | Domain event, never a direct send |
| anything → `billing` | **forbidden** | Billing subscribes to `*Paid` events |

The asymmetry between "call downward, event upward" is deliberate: synchronous
calls express *dependency*, events express *notification*. A module that must
know whether the other succeeded calls it. A module that merely wants others to
react publishes.

## 3. The `orders` question — where checkout lives

Tickets, memberships, season tickets, shop products and donations are all
purchasable. Three options were considered:

| Option | Consequence |
| --- | --- |
| Separate order model per module | Five checkouts, five refund flows, five fee calculations, no unified fan purchase history. Rejected. |
| One `commerce` module owns everything sellable | `commerce` becomes a god-module that must understand seat inventory and membership validity. Rejected. |
| **A shared `ordering` kernel in tier 2, with per-module fulfilment** | Chosen. |

`ordering` (a submodule of `commerce`, but with tier-2 dependency rules) owns
`order`, `order_line`, `cart`, pricing snapshots, totals, tax lines and refund
records. Each sellable domain registers a **line-type handler** implementing:

```python
class OrderLineHandler(Protocol):
    line_type: LineType                       # TICKET | SEASON_TICKET | MEMBERSHIP | PRODUCT | DONATION
    async def reserve(self, line: CartLine, ctx: OrderContext) -> Reservation: ...
    async def price(self, line: CartLine, ctx: OrderContext) -> PricedLine: ...
    async def fulfil(self, line: OrderLine, ctx: OrderContext) -> None: ...
    async def release(self, reservation: Reservation) -> None: ...
    async def reverse(self, line: OrderLine, amount: Money) -> None: ...
```

So checkout is one flow — reserve all lines → price → pay → fulfil all lines —
while seat locking stays inside `ticketing` and stock reservation stays inside
`commerce`. A mixed cart (2 tickets + a scarf + a €10 donation) works by
construction, which matters: it is a real matchday behaviour and retrofitting it
later would be a rewrite.

## 4. Enforcement

`import-linter` contracts in `backend/.importlinter`, run in CI:

```ini
[importlinter]
root_package = app

[importlinter:contract:tiers]
name = Module tiers
type = layers
layers =
    app.platform | app.billing | app.analytics
    app.payments | app.access_control | app.notifications | app.integrations
    app.players | app.training | app.ticketing | app.commerce | ...
    app.clubs | app.teams | app.staff | app.venues | app.competitions
    app.tenants | app.identity | app.people | app.audit | app.media | app.privacy
    app.core

[importlinter:contract:core-is-independent]
name = core imports no domain module
type = forbidden
source_modules = app.core
forbidden_modules = app.tenants, app.identity, ...

[importlinter:contract:no-cross-module-internals]
name = Modules may not import another module's repository, models or services
type = forbidden
source_modules = app.*
forbidden_modules = app.*.repository, app.*.models
allow_indirect_imports = false
```

The third contract is the important one. Cross-module access goes through a
module's public surface — `app.<module>` `__init__` re-exports the service
interface, DTOs and events, and nothing else. Importing
`app.ticketing.models.Ticket` from `app.loyalty` fails CI.

For pragmatism there is one documented exception list (`analytics` may read other
modules' models, because read models genuinely need joins). It is a single
contract entry, visible in review, not an ad-hoc habit.

## 5. Cross-module data access

Analytics and admin list screens need joins across module boundaries (e.g. "fans
with a membership who attended ≥ 5 matches and spent > €200 in the shop"). The
rule "no cross-module queries" would push us into N+1 service calls.

Resolution:

- **Transactional paths** never cross-join. They use service calls and events.
- **Reporting paths** use explicit, versioned **read models** owned by
  `analytics`: SQL views or materialised tables built by scheduled jobs and
  event handlers. They are declared in `analytics/read_models/`, are allowed to
  reference other modules' tables, and are the *only* place that is true.
- A read model is always rebuildable from source tables. We never treat one as
  the system of record.

This gives us join performance without dissolving boundaries, and it means that
if a module is ever extracted, exactly one place needs rework.

## 6. Shared kernel — what lives in `core`

Deliberately small. Everything here is domain-agnostic:

- `Money` value object (`amount_minor: int`, `currency: Currency`) with explicit
  rounding rules and no float constructor
- `TenantContext`, `RequestContext`, correlation IDs
- Base SQLAlchemy declarative classes and mixins (`TenantScoped`, `Timestamped`,
  `SoftDeletable`, `Auditable`)
- ID generation (UUIDv7 — time-ordered, index-friendly, non-guessable)
- `Clock` protocol (injectable; no `datetime.now()` in domain code, so time-based
  logic is testable)
- Error hierarchy and the HTTP error mapper
- Pagination primitives
- Ports: `StoragePort`, `CachePort`, `EventPublisher`

What must **not** drift into `core`: anything with a football concept in it. If
`core` ever imports the word "player", the boundary has failed.
