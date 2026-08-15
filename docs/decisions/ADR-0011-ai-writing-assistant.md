# ADR-0011 — One platform-held AI key, per-tenant entitlement and quota

**Status:** Accepted · **Date:** 2026-08-14

## Context

Club editors write the same handful of things over and over — a signing, a
departure, a match report — and most of them are not writers. The assistant is
there to tighten what a volunteer press officer already wrote, not to write for
them.

That raises two questions that have nothing to do with prompts:

1. **Whose key is it?** Asking every club to obtain and paste an Anthropic key
   is a non-starter: it puts a provider account, a payment method and a secret
   into the hands of a volunteer, and it makes the feature unusable for the
   clubs who most need it. The requirement given was the opposite — one key,
   confirmed once at platform level, usable by every tenant.
2. **Who pays, and how is that bounded?** With one shared key, every request a
   tenant makes is a cost the platform absorbs. An unbounded feature on a shared
   key is an unbounded bill, and one enthusiastic tenant can spend everyone's
   budget.

## Decision

**One platform key, held in the environment. Per-tenant policy expressed as
entitlements. Every call metered.**

- The key is read from `ANTHROPIC_API_KEY` (a secret manager in production). It
  is **not** stored in the database and there is no admin screen that sets it.
  A provider secret in the application database is one dump, backup, support
  export or over-broad `SELECT` away from disclosure, and the convenience of
  editing it in a browser does not pay for that risk. The super-admin console
  reports only whether a key is *present*.
- Whether a tenant may use the assistant is the boolean feature `ai_assist`.
  How much they may use is the quota `ai_requests_per_month`. Both are ordinary
  entries in the feature catalogue, resolved through the same plan → override →
  cache path as every other feature. The super-admin endpoint writes an
  entitlement override with a mandatory reason, so "why does this tenant have
  it?" always has an answer.
- Both default to **closed** (`ai_assist` off, quota `0`). Every other default
  in the catalogue leans open for core features; this one does not, because the
  cost of an open default lands on the platform rather than the tenant.
- Every call writes an `ai_usage` row — tenant, operation, model, tokens,
  duration, and whether the editor kept the suggestion. Written through the
  platform role in its own transaction: the tokens were spent whether or not the
  tenant's request goes on to succeed.

**The assistant proposes; the editor disposes.** No endpoint writes to an
article. `POST /ai/polish` returns a suggestion, the editor sees it side by side
with their own text, and it reaches the article only through the normal content
update route.

## Guardrails

- The system prompt's first rule is *never introduce a fact that is not in the
  draft*, and each article type names the facts that would cause a real
  correction if invented — a transfer fee, a scoreline, an appearance count.
- Output is constrained by a JSON schema over the four block types, with
  `additionalProperties: false`, and is then re-validated through the CMS block
  models. The schema stops the model returning shapes we do not render; the
  re-validation stops anything that satisfies the schema but not our rules.
- `stop_reason == "refusal"` is checked before any content is read, and surfaces
  as a 422 rather than an empty article.
- The draft is bounded before the call (block count and character count), so an
  accidental paste cannot turn into a large bill.
- The usage ledger stores **no prompt text and no article content** — only who
  asked for what, when, and what it cost. An unannounced signing is a story the
  club owns.

## Consequences

- A club needs no provider account, no payment method and no key. The feature is
  a line item on their plan, which is where they already expect it.
- The platform can see, per tenant, exactly what the feature costs and whether
  suggestions are being accepted — the only honest measure of whether it earns
  what it spends.
- Switching providers means writing one adapter behind `AiProvider`; nothing in
  the CMS knows which model answered.
- The quota is checked before the call and recorded after it, so two concurrent
  requests can both pass a check at the boundary. That is a deliberate trade: a
  serialised counter would put a lock on the hot path to prevent an overspend of
  one request.
- Turning the feature on for a tenant is a **step-up-authenticated** action
  (`platform.tenant.manage` is sensitive). Granting access to a key the platform
  pays for is exactly what a stolen session should not be able to do.
