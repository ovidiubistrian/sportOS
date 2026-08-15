# 08 — SaaS Billing

## 1. Two revenue streams, kept strictly apart

| | Stream A — Subscription | Stream B — Transaction fees |
| --- | --- | --- |
| Who pays | Tenant → us | Deducted from fan payments to the club |
| Mechanism | Stripe Billing (our own account) | Stripe Connect `application_fee_amount` |
| Cadence | Monthly / yearly, recurring | Per transaction, at capture |
| Our record | `tenant_subscription`, `platform_invoice` | `platform_fee_transaction` |
| VAT | We invoice the club (B2B, reverse charge in EU) | Fee is our service revenue to the club |

They never share a code path, a Stripe account, or a ledger table. Conflating
them is the most common way SaaS marketplaces produce unreconcilable books.

## 2. Plans are data

```
plan → plan_version → { plan_feature[], plan_price[] }
```

Versioning is the point. When pricing changes, we create `plan_version 2`;
existing subscriptions stay pinned to `version 1` until explicitly migrated. This
gives grandfathering for free and makes "what exactly did this tenant agree to in
March?" answerable.

`plan_price` is per `(currency, interval)`, each mapped to a Stripe Price ID. A
plan can be sold at €299/mo, £259/mo and 1 490 RON/mo without any code knowing
those numbers exist.

Indicative tiers (values illustrative — nothing is hardcoded):

| | STARTER | CLUB | PRO | ENTERPRISE |
| --- | --- | --- | --- | --- |
| Clubs / teams | 1 / 4 | 1 / 20 | 3 / unlimited | negotiated |
| Academy, CMS, website | ✓ | ✓ | ✓ | ✓ |
| Ticketing | — | GA only | GA + seated | ✓ |
| Memberships, shop | — | ✓ | ✓ | ✓ |
| Loyalty, resale, wallet | — | — | ✓ | ✓ |
| Custom domain | — | ✓ | ✓ | ✓ |
| Advanced analytics, SSO | — | — | ✓ | ✓ |

## 3. Billing policy — the commercial contract

`billing_policy` is separate from `tenant_subscription` because the *packaging*
(what features you get) and the *commercials* (what you pay) vary independently.
A tenant can be on the PRO feature set with a bespoke fee schedule.

```
billing_policy
  model: SUBSCRIPTION | TRANSACTION_FEE | HYBRID | ENTERPRISE
  currency, monthly_minor, yearly_minor
  effective_from .. effective_to        (non-overlapping, DB-enforced)
    └── billing_fee_rule[]
          category: TICKET | SEASON_TICKET | MEMBERSHIP | SHOP | DONATION | ACADEMY_FEE
          percentage_bp, fixed_minor, min_fee_minor, max_fee_minor
```

The four required models, expressed purely as data:

```
Subscription only    model=SUBSCRIPTION  monthly=29900 EUR   (no fee rules)
Transaction only     model=TRANSACTION_FEE  monthly=0
                       TICKET 400bp · SHOP 300bp
Hybrid               model=HYBRID  monthly=9900 EUR
                       TICKET 100bp · SHOP 100bp
Enterprise (example) model=ENTERPRISE  yearly=1490000 EUR
                       TICKET 100bp · SHOP 50bp · DONATION 0bp · ACADEMY_FEE 0bp
```

Policies are time-boxed and non-overlapping, enforced by a PostgreSQL exclusion
constraint (see [03 §17](03-data-model.md)). "Which fee applied to this order?"
therefore has exactly one answer, and historical fee calculations remain
reproducible after a renegotiation.

## 4. Fee calculation

Computed **at payment-intent creation**, not afterwards, because Stripe requires
`application_fee_amount` up front.

```python
def compute_platform_fee(order: Order, policy: BillingPolicy) -> Money:
    total = Money.zero(order.currency)
    for line in order.lines:
        if line.fee_category is None:          # SHIPPING, FEE lines are excluded
            continue
        rule = policy.rule_for(line.fee_category)
        if rule is None:
            continue
        fee = line.total.percentage(rule.percentage_bp) + rule.fixed
        fee = fee.clamp(rule.min_fee, rule.max_fee)
        total += fee
    return total.round_half_up()               # rounding happens once, at the end
```

Rules that took discussion and are therefore written down:

- Fees apply to **line totals after discount**, not to list price.
- **Shipping and payment surcharges are never fee-bearing.** Charging a
  percentage of postage is indefensible to a customer.
- Rounding happens once on the order total, not per line — per-line rounding
  drifts by cents that never reconcile.
- Currency conversion is never applied: the fee is in the order's currency.
- A `0 bp` rule and a *missing* rule are different. Missing means the category
  was never negotiated → fee is zero, but it is flagged in the platform revenue
  report as unpriced, so we notice.

Every computed fee is written to `platform_fee_transaction` at capture — our own
ledger, independent of Stripe, which is what reconciliation compares against.

## 5. Refunds and fee reversal

Policy: **platform fees are refunded proportionally when the club refunds a
fan.** Stripe supports `refund_application_fee`.

Rationale: the alternative (we keep our fee on a cancelled match) makes the club
lose money on every refund and is the single fastest way to destroy trust with a
customer whose stadium just got waterlogged. The cost to us is bounded and
predictable.

Exception, configurable per policy: `retain_fee_on_refund` for enterprise
contracts that negotiate it explicitly. Default `false`.

Partial refunds reverse the fee pro rata on the refunded amount. Every reversal
is a new `platform_fee_transaction` row with a negative `fee_minor` — never an
update. Ledgers are append-only.

## 6. Dunning

| Day | Action |
| --- | --- |
| 0 | Payment fails → `PAST_DUE`, email to billing contact, in-app banner |
| 3 | Retry + reminder |
| 7 | Retry + reminder, tenant owner copied |
| 14 | Final notice, warns of suspension date |
| 21 | `SUSPENDED` — admin read-only; **scanning, refunds and public match info stay live** |
| 60 | Contract termination process (manual, commercial decision) |

Stripe's smart retries drive the schedule; our state machine reacts to
`invoice.payment_failed` / `invoice.paid` webhooks. Suspension is never automatic
within 21 days and never touches matchday operations.

## 7. Platform revenue reporting

Metrics the super-admin dashboard exposes, and their definitions — written down
because ARR disputes are always definitional:

| Metric | Definition |
| --- | --- |
| MRR | Sum of active subscriptions normalised to a month; annual plans ÷ 12. Excludes trials, credits, one-offs, transaction fees. |
| ARR | MRR × 12. Not a forecast. |
| Transaction revenue | `SUM(platform_fee_transaction.fee_minor)` over the period, net of reversals |
| GMV | Gross value of fan-side orders processed, by category |
| Net revenue | MRR + transaction revenue − provider costs |
| Churn | Tenants moving to `CLOSED` in period ÷ tenants active at period start |
| Net revenue retention | Cohort revenue this period ÷ same cohort last period |

Multi-currency: each metric is stored per currency and converted for the roll-up
using the **rate on the transaction date**, stored on the record. We never
re-convert historical figures at today's rate — that makes last month's reported
MRR change, which is unacceptable in a financial report.

## 8. Academy fees (worth flagging)

Academy fees are a fan/parent-side payment (parent → club), so they belong in
Stream B with their own `billing_fee_rule` category. Two properties make them
different from every other purchase:

- They are **recurring** (monthly training fees), which means Stripe subscriptions
  on the *connected account*, not one-off payment intents.
- They are frequently **partially paid, deferred, waived or scholarship-funded**,
  by arrangement with individual families.

This makes academy fee collection a genuinely separate feature, not a variant of
shop checkout. It is scheduled for Phase 2 with its own design pass. Phase 1
records fee *obligations* and payment status entered by staff, without taking
money online — which is what a club migrating from spreadsheets actually needs
first.
