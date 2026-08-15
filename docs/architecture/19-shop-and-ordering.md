# 19 — The shop, and the ordering kernel under it

Gate 1 ships one sellable thing: club shop products, paid for at the counter.
The structure underneath it is the one from
[ADR-0005](../decisions/ADR-0005-ordering-kernel.md), because tickets,
memberships and donations arrive at Gate 2 and a second checkout would be a
rewrite rather than an addition.

## Two modules

`app/ordering` (tier 2) owns `cart`, `cart_line`, `shop_order`,
`shop_order_line`, and the handler registry. It knows how to price, place and
fulfil an order. It does not know what a product is.

`app/commerce` (tier 3) owns `product` and `product_variant`, and registers a
`PRODUCT` handler. The dependency points from commerce to ordering, never back
— that inversion is the ADR's cost and the registry is what pays it.

Adding tickets means adding `app/ticketing` with a `TICKET` handler. Nothing in
`ordering` changes, and a mixed basket works because it always did.

## What is snapshotted, and why

An order line carries its own `description`, `unit_price_minor` and `quantity`.
The club will rename products, reprice them and delete the ones it no longer
stocks; none of that may change what a supporter was charged or what the receipt
says they bought. The `reference_id` is polymorphic with no foreign key, which
is the other cost the ADR accepted.

## Stock

Stock lives on the *variant*, never the product — otherwise a product with sizes
and a product without keep it in different places and every query handles both.
A product created with no variants gets one called "One size".

The handler decrements inside the checkout transaction and re-checks first, so
two supporters buying the last scarf cannot both succeed. The loser gets a 422
and no order: nobody has been charged, because Gate 1 takes payment at the
counter. When cards arrive, the failure policy changes to the ADR's — payment
stands, good lines fulfil, failed lines auto-refund — and that is a change
inside `checkout`, not a new flow.

## The supporter side

Unauthenticated. A basket is identified by an opaque cart token, and by nothing
else: requiring an account to buy a scarf is how a club loses the sale. The
token lives in an httpOnly cookie set by a Next route handler
(`app/api/basket`), so the browser still never talks to the API directly and the
page's own scripts cannot read it.

`PUT /public/basket/lines` **sets** a quantity rather than adding one, so a
double-tapped button cannot order two scarves.

Everything is scoped by the `Host` the visitor arrived on. There is no club
parameter — a token from one club's shop opens a fresh, empty basket at another.

## Two things this uncovered

**A new tenant had no plan at all.** Self-serve registration created the tenant
and stopped, so entitlements fell back to the two features that default open and
a club that had just signed up found the shop, ticketing and memberships all
answering 402 with nothing on screen explaining why. Registration now starts a
30-day trial of the CLUB plan — the trial shows what the product does, which a
trial that hides half of it behind an upgrade prompt does not.

**Currency was hardcoded to EUR.** The sign-up form already asks for a country;
`app/core/countries.py` now answers currency and default language from it. A
Romanian club prices in lei without being asked to confirm it. Unknown countries
fall back to EUR and English rather than being refused.

Both caches — permissions and entitlements — are keyed by a version counter that
only a *write* bumps. Changing a role template or backfilling a subscription
touches neither, so `seed_reference_data` now clears the permission prefix
explicitly. Without it a deploy that adds a permission appears to do nothing.

---

# The super-admin console

`/platform` in the admin app, `app/platform/router.py` behind it. Two jobs that
cannot be done from inside a tenant: who is on the platform and what they pay
for, and the competition catalogue every tenant reads.

## Platform access is not tenant access

The console counts a tenant's clubs and players through `platform_session`,
which bypasses RLS and states a reason on every entry. It cannot *read* those
players: `get_context` only honours an `X-Tenant-Id` the caller holds a live
role in, and a super admin holds none. Asking for one returns
`TENANT_CONTEXT_MISSING`, which `tests/platform/test_console.py` asserts
alongside the fact that the count was available.

## Impersonation is a grant, not a flag

Because the request path already refuses a tenant you hold no role in, the safe
way in is to genuinely have one. `POST /platform/tenants/{id}/impersonate`
writes a real `role_assignment` with a `valid_until`, a `granted_by` and a
required reason, at CLUB_ADMIN rather than TENANT_OWNER — support needs to see
what the club sees, not to grant roles or change the subscription.

It sits behind step-up authentication, so a password-only session is refused
before anything is written. That is also why the tenant-write routes have no
end-to-end success test: reaching one would mean weakening the permission.

Building this found that `tenant_memberships` filtered only `revoked_at` and not
`valid_until`, while the permission resolver had always honoured both. A lapsed
grant therefore let its holder *enter* a tenant with no permissions inside it —
the wrong shape of refusal, and it would have made a time-limited impersonation
not actually time-limited.

## Curation is separate from tenant management

`platform.competition.manage` is a distinct, non-sensitive permission. The
Romanian second division is not anybody's private information; suspending a
tenant or moving it between plans is, and those stay behind step-up.

A competition is withdrawn rather than deleted — `is_active` false takes it out
of what clubs can enter while leaving every season already filed against it
intact. The console shows that count next to each row, and refuses to let the
key be edited once it is non-zero.
