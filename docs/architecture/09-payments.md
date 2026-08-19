# 09 — Payment Architecture

## 1. The port

`payments` exposes a provider-agnostic interface. No module outside `payments`
imports `stripe`, and CI enforces that with an import contract.

```python
class PaymentProvider(Protocol):
    # Fan-side (money to a club's connected account)
    async def create_payment(self, req: PaymentRequest) -> PaymentIntentResult: ...
    async def confirm_payment(self, ref: ProviderRef) -> PaymentStatus: ...
    async def get_payment_status(self, ref: ProviderRef) -> PaymentStatus: ...
    async def refund(self, req: RefundRequest) -> RefundResult: ...

    # Platform-side (SaaS subscriptions to us)
    async def create_subscription(self, req: SubscriptionRequest) -> SubscriptionResult: ...
    async def update_subscription(self, ref: ProviderRef, req: SubscriptionUpdate) -> SubscriptionResult: ...
    async def cancel_subscription(self, ref: ProviderRef, at_period_end: bool) -> SubscriptionResult: ...

    # Connected accounts
    async def create_connected_account(self, req: AccountRequest) -> AccountResult: ...
    async def get_onboarding_link(self, ref: ProviderRef, return_url: str) -> str: ...
    async def get_account_status(self, ref: ProviderRef) -> AccountStatus: ...

    # Inbound
    def verify_webhook(self, payload: bytes, headers: Mapping[str, str]) -> ProviderEvent: ...
```

The types crossing this boundary (`Money`, `PaymentStatus`, `ProviderRef`) are
ours. Stripe objects never escape the adapter. The test for whether the
abstraction is real: `MockPaymentProvider` must be able to drive the entire
checkout test suite, including 3DS-required and failure paths. It does.

## 2. Two flows

```
SaaS:   Tenant ──► Stripe Billing ──► Football Club OS account
Fan:    Fan ──► Checkout ──► Stripe Connect ──► Club's connected account
                                   └─ application_fee_amount ──► our account
```

Separate Stripe API keys, separate webhook endpoints, separate handler modules,
separate ledgers.

## 3. Direct charges vs destination charges — the decision

This is the most consequential payments choice and it is not reversible cheaply.

| | **Direct charges** (recommended) | Destination charges |
| --- | --- | --- |
| Merchant of record | The club | **Us** |
| Charge created on | Connected account | Platform account |
| Dispute liability | Club | **Us** |
| Refund liability if club has no balance | Club | **Us** |
| Consumer contract, refund policy, terms | Club's | Ours to defend |
| VAT on the ticket/goods | Club's obligation | Arguably ours — very bad |
| Card statement descriptor | Club's name | Ours, or a soft descriptor |
| Payout timing control | Club's schedule | Ours |
| Our access to payment data | Via `Stripe-Account` header | Direct |

**Recommendation: direct charges with `application_fee_amount`.**

The decisive arguments are legal, not technical. With destination charges we
become the merchant of record for the sale of match tickets and football shirts
across multiple EU jurisdictions. That drags in consumer-protection obligations,
VAT registration questions in each country, and — most dangerously — **chargeback
liability for events we do not control**. A cancelled fixture at a 20 000-capacity
club could produce five figures of disputes landing on us for a customer paying
€149/month. That is an unbounded, uninsured liability sitting on a small SaaS
business.

Direct charges put the sale where it legally belongs: between the club and its
supporter. We take a service fee for providing the platform.

Cost of this choice, accepted:
- Every API call needs the `Stripe-Account` header — handled once, in the adapter.
- Webhooks arrive on the connected account and must be routed to the right
  tenant — handled by the `account` field on the event.
- Onboarding friction is higher: the club must complete full Stripe KYC before
  selling anything. We surface this as a first-class onboarding checklist in
  admin-web and as a blocking indicator in super-admin.
- Refunds require the club to hold balance. We detect and surface negative
  balance rather than discovering it during a refund.

See [ADR-0007](../decisions/ADR-0007-stripe-connect-charge-model.md).

## 4. Checkout flow

```
1. POST /api/v1/checkout/sessions          Idempotency-Key required
   ├─ reserve every line via its OrderLineHandler   (seats HELD, stock reserved)
   ├─ price lines, apply member benefits + discounts
   ├─ compute tax lines
   ├─ compute application fee from the tenant's billing policy
   ├─ create order (status = AWAITING_PAYMENT)
   └─ create PaymentIntent on the connected account
        → returns client_secret
2. Browser confirms with Stripe Elements/Payment Element (SCA/3DS handled by Stripe)
3. Webhook payment_intent.succeeded  ──►  the authoritative signal
   ├─ persist provider_event  (UNIQUE on provider_event_id)  → 200 immediately
   └─ async: mark order PAID → fulfil each line → emit OrderPaid
4. Fulfilment per line type
   ├─ TICKET          seats SOLD, ticket rows ISSUED, credentials minted
   ├─ MEMBERSHIP      membership ACTIVE
   ├─ PRODUCT         stock committed, fulfilment task queued
   └─ DONATION        campaign total updated, receipt issued
5. OrderPaid consumers: loyalty, notifications, analytics, billing fee ledger
```

Two rules that prevent the classic failure modes:

- **The browser never confirms an order.** A user closing the tab mid-payment
  must still receive their ticket; the webhook is the source of truth. The
  success page polls order status rather than asserting it.
- **Reservations survive payment latency.** Holds are extended to cover 3DS
  challenges (which can take minutes), and released only on explicit failure,
  cancellation or expiry.

## 5. Idempotency

| Layer | Mechanism |
| --- | --- |
| Client → our API | `Idempotency-Key` header, stored in `idempotency_key`, replays the recorded response |
| Our API → Stripe | Deterministic idempotency key derived from `order_id` + operation |
| Stripe → our webhook | `UNIQUE (provider, provider_event_id)`; duplicate delivery is a no-op |
| Fulfilment handlers | `processed_event (handler_name, event_id)` primary key |
| Order creation | `UNIQUE (tenant_id, idempotency_key)` on `order` |

Stripe delivers webhooks at least once and *out of order*. Handlers are therefore
written to be order-independent: a `payment_intent.succeeded` arriving after a
`charge.refunded` must not resurrect the order. Every handler asserts the
expected current state and ignores stale transitions, rather than blindly
applying them.

## 6. Webhook processing

```
receive → verify signature (raw body, constant-time) → persist provider_event
        → return 200 within ~1s → process asynchronously via Celery
```

Returning 200 before processing is deliberate: slow processing causes Stripe
retries, retries cause duplicate work, and a 500 from a downstream bug would put
the endpoint into backoff exactly when volume is highest. Persisting first means
we can always replay.

Failed processing retries with exponential backoff, then moves to `FAILED` and
raises an alert. `provider_event` rows are retained 90 days and are replayable
from the super-admin UI — which has repeatedly proven to be the single most
valuable operational tool in systems like this.

Signature verification uses the **raw request body**. FastAPI's automatic JSON
parsing must be bypassed for these routes or verification silently fails on
whitespace differences.

## 7. Money handling

- `Money(amount_minor: int, currency: Currency)`. No float constructor exists.
- The ISO 4217 exponent comes from a table, not a hardcoded `100` — JPY has 0
  decimals, BHD/KWD/TND have 3. A hardcoded `/100` produces a 1000× error in
  Kuwait, which is exactly the kind of bug that only appears after the first
  international customer.
- Arithmetic across currencies raises. There is no implicit conversion anywhere.
- Splits (fee allocation, partial refunds) use largest-remainder distribution so
  the parts always sum exactly to the whole.
- Display formatting is a frontend concern using `Intl.NumberFormat` with the
  user's locale — never string concatenation of a symbol.

## 8. VAT and tax (flagged as unresolved)

Two distinct tax problems, often wrongly merged:

**(a) Our SaaS invoice to the club.** B2B within the EU with a valid VAT number →
reverse charge. Domestic → domestic VAT. Outside the EU → outside scope. Handled
by Stripe Tax on our Billing account. Tractable.

**(b) The club's sale to the fan.** The club is the merchant of record (direct
charges), so this is the club's VAT obligation — but *we* generate the receipt
and calculate the tax lines. Rates differ by country and by category: match
tickets are frequently reduced-rate or exempt as cultural/sporting events, while
merchandise is standard-rate. Romania, Germany, Spain and the Netherlands all
treat these differently.

What we build in Phase 2: a `tax_class` per sellable item and a per-club
`tax_rate` configuration table with effective dates, with rates entered by the
club (who has an accountant) rather than inferred by us. Tax lines are computed
at order time and snapshotted onto `order_line`.

What we explicitly do **not** do: claim to determine correct VAT treatment
automatically. The terms of service must state that tax configuration is the
club's responsibility. Getting this wrong is a liability we cannot carry, and
"the software calculated it" is not a defence a tax authority accepts.

See [open questions](open-questions.md#q4).

## 9. Payouts

Payouts go from the connected account to the club's bank on the club's own Stripe
schedule. We do not hold, route or touch fan money at any point — which is
precisely what keeps us outside payment-institution licensing requirements.

We display payout status in admin-web (read-only, from Stripe) so the finance
manager has one place to look, and surface `charges_enabled` /
`payouts_enabled` / outstanding `requirements` prominently — an incomplete
Stripe onboarding is the #1 reason a club cannot sell tickets, and it must be
impossible to miss.

## 10. What we never do

- Store, log, or proxy card data. PAN never touches our infrastructure; we use
  Stripe Elements / Payment Element so the fields are in Stripe's iframe and we
  stay in **SAQ-A** scope.
- Compute money in the frontend. Displayed totals come from the server.
- Trust a client-submitted price, quantity, discount or fee.
- Delete a payment, refund or fee record. Corrections are new rows.


## Credentials at rest

A club's gateway password is encrypted before it is stored, with Fernet, under
`SECRET_ENCRYPTION_KEY`. See `app/core/secrets.py`.

This reverses an earlier position, and the reasoning is worth keeping because
the earlier one was not wrong so much as answering a different question.

**The earlier argument.** The database already holds every supporter's order
and email address; it is the trust boundary. A key sitting beside it in the
same environment does not change what an attacker running as the application
can read. Encryption there is ceremony.

**What changed it.** That reasoning covers a breach and ignores the thing that
actually happens: dumps travel. They get copied to a laptop for debugging,
attached to a support thread, restored into staging. Every one of those is a
list of working credentials for other people's bank accounts, and none of them
carries the environment. The key and the data now have to be stolen separately.

**What it does not buy**, stated so nobody assumes otherwise: nothing against
code running as the application, which can read the key. This is protection for
data at rest and in transit between environments, not defence in depth against
compromise of the API.

**Decisions taken with it:**

- **AEAD, not CBC.** Fernet authenticates the ciphertext. Unauthenticated CBC is
  malleable by anyone with write access to the database, and hand-rolled padding
  invites padding oracles.
- **A missing key stops the application** in production, checked at startup.
  There is no fallback to a constant and no fallback to base64 when the library
  is absent — both are ways of turning encryption off without telling anybody.
- **Encrypted values are marked** with `enc:v1:`. That is what makes the
  migration idempotent and what let existing rows be migrated in place: `decrypt`
  returns an unmarked value unchanged, so nothing broke on the way.
- **A wrong key raises** rather than returning a mangled string. A corrupted
  password sent to a bank surfaces as the bank rejecting the club, which nobody
  would trace back to a key rotation.
