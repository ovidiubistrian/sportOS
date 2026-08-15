# ADR-0005 — One ordering kernel with per-domain line handlers

**Status:** Accepted · **Date:** 2026-08-13 · **Implemented:** 2026-08-15 (products only — see [19](../architecture/19-shop-and-ordering.md))

## Context

Five things are purchasable: tickets, season tickets, memberships, shop products
and donations. Later: academy fees and resale.

Each has different reservation semantics (seat locking vs stock reservation vs
nothing) and different fulfilment (mint a credential vs activate a membership vs
pick and pack). All share: pricing, discounts, member benefits, tax, payment,
refunds, platform fees, receipts and purchase history.

A fan at a match buys two tickets, a scarf and adds a €10 donation — in one
transaction, with one payment.

## Options

**A. An order model per module.** Five checkouts, five refund flows, five fee
calculations, five payment integrations. No unified purchase history. A mixed
cart is impossible without a distributed transaction across our own modules.

**B. `commerce` owns everything sellable.** Becomes a god-module that must
understand seat inventory, membership validity and campaign accounting.

**C. A shared ordering kernel with registered line handlers.**

## Decision

**Option C.** `ordering` owns `cart`, `order`, `order_line`, pricing snapshots,
tax lines, totals, refunds and fee categorisation. Each sellable domain registers
an `OrderLineHandler` implementing `reserve` / `price` / `fulfil` / `release` /
`reverse` (see [02 §3](../architecture/02-domain-boundaries.md)).

Checkout is one flow — reserve all lines → price → pay → fulfil all lines — while
seat locking stays in `ticketing` and stock reservation stays in `commerce`.

## Consequences

**Good.**
- Mixed carts work by construction. This is real matchday behaviour and
  retrofitting it later would be a rewrite.
- One place implements idempotency, price snapshots, refunds, tax lines and
  platform fees — the parts where a bug costs money.
- A new sellable type (academy fees, hospitality packages) is one handler, not a
  new checkout.
- Fan purchase history is one query.

**Bad.**
- `ordering` must be tier-2, below the domains it serves, which inverts the
  intuitive direction. Enforced by import contracts and easy to get wrong in
  review.
- `order_line.reference_id` is polymorphic with no database-level FK. Mitigated
  by the handler registry validating `line_type` and by a nightly referential
  integrity check.
- A partial fulfilment failure (tickets issued, shop item out of stock) needs an
  explicit policy: **the payment stands, successful lines fulfil, failed lines
  are auto-refunded and the buyer is notified**. Refusing the whole order after
  capture is worse for everyone.
