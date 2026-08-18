# 22 — Integration patterns: who owns the account at the provider

Adapted from a working production implementation of the same three patterns in
another multi-tenant SaaS (Oblio, Stripe, OpenAI). Every ⚠️ below is a bug that
was found in production there, not a hypothetical. Where this platform already
solves one, that is stated — so the same ground is not paid for twice.

## The question to answer first

Before writing a line for any new integration: **who owns the account at the
provider?** The answer decides entirely where the credentials live. There are
three cases, and mixing them is the source of most of the bugs below.

| | **A. Per tenant** | **B. Platform → tenant** | **C. Platform, shared** |
| --- | --- | --- | --- |
| The account belongs to | the tenant | us | us |
| Examples | BT iPay, Oblio (club invoices its supporters) | Stripe subscriptions, Oblio (we invoice the club) | Anthropic, API-Football |
| Credentials in | `payment_credential`-style table, one row per `(tenant_id, provider)` | platform config, encrypted | environment / secret manager |
| Set by | the club, in its own screens | platform operator | platform operator |
| Tenant can see them | yes, they are theirs — but the secret **never** in an API response | no | **never** |
| Per-tenant cost cap | not needed, they pay the provider | not needed | **required** |
| Metering | no | no | **required, per tenant** |

⚠️ **The most expensive trap.** The same provider can appear in two patterns at
once. Oblio would be both A (a club invoicing a supporter) and B (us invoicing
the club). Treated as one integration, subscription invoices come out of a
club's own numbering series, or the reverse. **They are two integrations that
happen to share an SDK.** Separate config, separate series, separate tests.

## What this platform already has

| Pattern from the source document | Here |
| --- | --- |
| Stateless provider contract | `payments/registry.py` — `build_provider(session, tenant_id, provider)`; credentials are passed per call, never held on the instance |
| Per-tenant credential table | `payment_credential`, unique on `(tenant_id, provider)` |
| Accept both key spellings | `_setting(settings, "user_name", "userName")` |
| Never save untested credentials | `POST /payments/settings/{provider}/test` |
| Secrets never leave | responses carry `has_password: bool`; the password is not in the schema |
| 402, not 403, for a spent budget | `FeatureNotEnabled` is already 402 with structured detail |
| Test with credentials not yet saved | the test endpoint accepts them in the body |
| Metering a shared key | `app/ai/` records usage and enforces quota |
| Tenant scoping from the session, never a parameter | structural: forced RLS on every table, `tenant_id` from request context, swept by `tests/isolation/` |

## What is genuinely missing

- **Pattern B in full.** Stripe subscriptions, platform billing config, automatic
  invoice emission. None of it exists.
- **Oblio**, in either pattern.
- **A billing idempotency table** with the ordering below. The pattern exists for
  scans (`scan_log`), not for invoices.
- **The access gate** — `Entitlement` and plans exist; suspend, postpone and
  unblock do not.

## Idempotency: reserve the row *before* calling the provider

⚠️ The obvious order — `SELECT existing` → call provider → `INSERT` — issues two
invoices under two concurrent webhooks, because both pass the SELECT. Stripe
replays events, so this is not theoretical. In Romania a duplicate fiscal
invoice is cleared only by a credit note.

Reserve first: insert the key, let the unique constraint reject the loser, and
only then call the provider. Fill the series and number into the reserved row
afterwards. Send the key as an `Idempotency-Key` header too, where supported.

## Stripe: the signature check must fail closed

⚠️ The original implementation fell back to `json.loads(body)` when the webhook
secret was unset — and in production it *was* unset. Anyone could POST a forged
event, extend their own subscription and trigger a real fiscal invoice.

A missing secret must refuse the request (503), never accept it. Add a startup
check that refuses to boot in production without it.

⚠️ Stripe sends **both** `checkout.session.completed` and
`invoice.payment_succeeded` for a subscription's first payment. Pick one as the
source of truth and skip `billing_reason == "subscription_create"` on the other,
or every new subscriber is invoiced twice.

⚠️ Do not return 5xx for errors a retry cannot fix. Stripe will replay for days.
A missing tax number is not transient: log, alert, return 200.

⚠️ Payments taken outside Stripe — bank transfer, cash, a "mark as paid" button —
must go through the *same* invoice path with their own idempotency key.
Otherwise exactly the largest payments are the uninvoiced ones.

## Oblio: read the PDF, not the status code

⚠️ The tax number goes in `cif`. Sending `code` is accepted without error and
produces an invoice reading `CIF: -`, which is useless to the client's
accountant. On any new provider, issue a test invoice and **read the document**.

⚠️ Invoice the legal entity, not the tenant. A club has a trading name; an
invoice needs the registered name, tax number and address. Block checkout when
those are missing rather than issuing something that must be reversed.

⚠️ There must always be a fallback that depends on no external provider, because
most tenants will never configure one.

## Shared keys: the gate comes before the call

⚠️ Check the cap *before* calling the provider, or a tenant over their limit
keeps costing money on every request — paid for, then refused.

⚠️ Meter in a `finally`. A 200 that fails to parse was still billed.

⚠️ Return the provider's whole response body from the wrapper, not just the
text. Dropping `usage` means cost cannot be computed, and adding it back means
touching every caller.

⚠️ Keep the price table in the database and snapshot the cost at call time. A
provider's price change must not rewrite history.

⚠️ Store the period as indexed `year`/`month` columns. `WHERE created_at >=
date_trunc('month', now())` puts a scan on the critical path of every AI call.

## The access gate

Three states — `allowed`, `payment_required`, `blocked` — evaluated in one
place. Trial and paid are both `allowed`; the difference is status, not access.

⚠️ Some routes must stay reachable in `payment_required`, or the tenant cannot
pay. ⚠️ Operational accounts and platform staff bypass the gate entirely — a
steward must be able to scan tickets while the club's invoice is overdue.
⚠️ Public endpoints never pass through it: a lapsed subscription must not stop
a club's own supporters from buying.

⚠️ If it ships behind a flag, put turning the flag on in the same sprint. In the
source implementation the flag was never enabled and the whole mechanism was
dead code for months.

## Secrets

⚠️ Never in a tracked file. The source implementation kept a live API key in
`data/ai_config.json`, committed and copied into every Docker image — and
runtime edits to it vanished on the next build.

⚠️ Use AEAD. Unauthenticated AES-CBC with hand-rolled padding is malleable and
invites padding oracles. `Fernet` or AES-GCM.

⚠️ Never fall back to a hardcoded key, and never fall back to base64 when the
crypto library is missing. Fail loudly at startup instead.

**Where this platform stands.** `payment_credential.settings` is stored
unencrypted, and that is a recorded position rather than an oversight — see the
module docstring in `app/payments/models.py`. The argument there is that the
database is already the trust boundary. The counter-argument, which this
document makes, is a leaked backup. Worth revisiting; the decision belongs in
`09-payments.md`.

## Order of implementation

1. Secret registry, AEAD encryption, startup check. Everything else rests on it.
2. Oblio as pattern A, on the existing provider contract.
3. The billing idempotency table, with the reservation ordering above.
4. Pattern B: plans, checkout, signed webhook, then automatic invoicing.
5. The manual payment route, through the same emitter.
6. Cost caps and metering for shared keys.
7. The access gate — and enabling it.

Write the cross-tenant isolation test before each feature. It is the only class
of bug here that is invisible in the interface and surfaces when one customer
sees another's data.
