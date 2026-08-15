# ADR-0007 — Stripe Connect direct charges

**Status:** **Proposed** — requires founder + legal sign-off before Phase 2
· **Date:** 2026-08-13

## Context

Fans pay clubs for tickets, memberships, merchandise and donations. We take a
platform fee. Stripe Connect offers two models, and the choice determines who is
legally the seller.

## Options

| | **Direct charges** | Destination charges |
| --- | --- | --- |
| Charge created on | Connected (club) account | Platform account |
| Merchant of record | Club | **Us** |
| Dispute/chargeback liability | Club | **Us** |
| Refund when club has no balance | Club's problem | **Our** problem |
| Consumer contract and refund policy | Club's | Ours to defend |
| VAT on tickets and goods | Club's obligation | Arguably ours |
| Card statement descriptor | Club's name | Ours |
| Onboarding friction | Higher — full KYC before selling | Lower |
| Our access to payment data | Via `Stripe-Account` header | Direct |

## Decision

**Direct charges**, with `application_fee_amount` for the platform fee.

## Rationale

The decisive arguments are legal and financial, not technical.

With destination charges we become the merchant of record for the sale of match
tickets and football shirts across multiple EU jurisdictions. That brings:

- **Chargeback liability for events we do not control.** A cancelled fixture at a
  20 000-capacity club could generate five figures of disputes landing on us —
  from a customer paying €149/month. An unbounded, uninsured liability against a
  small, fixed revenue per customer.
- Consumer-protection obligations in each country where a fan buys.
- VAT registration questions in each of those countries.
- Responsibility for the club's own refund policy.

Direct charges put the sale where it legally belongs: between the club and its
supporter. We provide software and charge a service fee.

## Consequences

**Accepted costs.**
- Every Stripe call needs the `Stripe-Account` header — handled once, in the
  adapter.
- Webhooks arrive on connected accounts and must be routed by the event's
  `account` field.
- Clubs must complete full Stripe KYC before selling anything. This will delay
  the pilot if started late, so onboarding begins in **week 1 of Phase 2**, not
  at the end. It is surfaced as a blocking checklist in admin-web and as a
  first-class indicator in super-admin.
- Refunds require the connected account to hold balance. We surface negative
  balance proactively rather than discovering it during a refund.
- Some reporting requires per-account API calls rather than one platform query.

**Reversibility: poor.** Changing the model later changes the merchant of record
on all future transactions, splitting historical reporting and requiring new
terms of service for both clubs and fans. This is why it needs a signed decision
before any payment code exists.

**Open sub-decision.** Connected account at **club** level, not tenant level —
see [Q8](../architecture/open-questions.md#q8).
