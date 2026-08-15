# Open Questions & Architectural Contradictions

Points where the brief contains a genuine tension, where a requirement cannot be
fully satisfied as stated, or where a decision needs a commercial/legal owner
rather than a technical one. Nothing here has been silently resolved.

Each carries a recommendation and a deadline — the phase by which the decision
must be made or the work it blocks.

---

## Q1 — "Modular monolith" vs the scanner's availability requirement

**Tension.** The brief mandates a modular monolith and no premature services. It
also requires scanning to work when the stadium network is degraded. These are
compatible for the *pilot* but not indefinitely: a 40 000-capacity venue with 30
gates cannot depend on a WAN round-trip per scan.

**Assessment.** Not a contradiction today. The offline manifest model
([ADR-0006](../decisions/ADR-0006-ticket-credentials.md)) makes the monolith
sufficient at pilot scale, and `access_control` is the module most cleanly
extractable later — it depends only on credential validation and an append-only
scan log.

**Recommendation.** Keep the monolith. Design the credential format and the scan
API so a stadium-local validation service could serve them unchanged. Revisit if
a venue exceeds ~15 000 capacity or a club requires a hard on-premises SLA.

**Decide by:** not blocking. Re-evaluate before the second stadium deployment.

---

## Q2 — White-label custom domains vs a hosted Keycloak login

**Tension.** The product promises the club's own domain and controlled branding.
A fan clicking "Sign in" on `fcexample.com` lands on `auth.footbola.io`. That is
visible third-party branding inside a checkout the club considers theirs — and
some clubs will object loudly.

**Options.** Themed Keycloak login (cheap, domain still visible) · per-tenant
CNAME with automated certificates (removes it, costs onboarding automation) ·
direct-grant embedded login (rejected — we would handle passwords, and lose MFA
and social login).

**Recommendation.** Ship the themed login in Phase 1. Build per-tenant auth
CNAMEs in Phase 2, gated behind the `custom_domain` entitlement, for clubs that
ask. Detail in [05 §7](05-identity-and-authentication.md).

**Decide by:** Phase 2 start. **Owner:** product + infrastructure.

---

## Q3 — Direct vs destination Stripe charges

**Tension.** Destination charges give us cleaner data access and control. Direct
charges put legal liability where it belongs. The brief asks for a platform fee
and for European compliance without stating who is merchant of record.

**Recommendation.** **Direct charges.** Reasoning in
[09 §3](09-payments.md#3-direct-charges-vs-destination-charges--the-decision)
and [ADR-0007](../decisions/ADR-0007-stripe-connect-charge-model.md). The
decisive factor is chargeback liability: with destination charges, a cancelled
fixture at a 20 000-capacity club could put five figures of disputes on a
business earning €149/month from that customer.

**This decision is expensive to reverse** — it changes the merchant of record on
every historical transaction. It needs an explicit sign-off, ideally with legal
input.

**Decide by:** before any payment code is written (Phase 2 start).
**Owner:** founder + legal counsel.

---

## Q4 — VAT on club sales

**Tension.** The brief requires no hardcoded taxation and international
usability. But we generate the receipt and compute the tax lines while the *club*
carries the VAT obligation. Rates differ by country and category — match tickets
are frequently reduced-rate or exempt as sporting/cultural events while
merchandise is standard-rate, and Romania, Germany, Spain and the Netherlands all
treat this differently.

**Recommendation.** Per-club tax configuration with effective dates and a
`tax_class` per sellable item; rates **entered by the club**, whose accountant
owns them. Tax lines snapshotted onto `order_line` at purchase. The terms of
service must state that tax configuration is the club's responsibility.

We must not claim to determine correct VAT treatment automatically. "The software
calculated it" is not a defence a tax authority accepts, and the liability is
unbounded relative to our revenue per customer.

**Decide by:** before Phase 2 checkout is built. **Owner:** legal + finance.

---

## Q5 — Offline scanning cannot prevent all duplicate entry

**This is a mathematical limit, not an implementation gap.** Two scanners that
are disconnected from the server *and* from each other cannot both know that a
credential was used at the other gate. No design fixes this. It must be a stated
product decision, not a discovered surprise.

**Mitigations that reduce, not eliminate, the exposure:**

- Gate-partitioned manifests: a credential valid only at Gate B is not in Gate
  D's manifest, so cross-gate duplication is impossible for seated tickets.
- Peer sync over the venue LAN when the WAN is down (Phase 4).
- Offline scans sync continuously; the window is usually seconds, not minutes.
- Post-match reconciliation flags every duplicate with gate, device and operator,
  so abuse is detectable even when it was not preventable.
- Offline mode is an explicit, audited operator action with a visible banner —
  not a silent fallback.

**Residual risk.** Bounded, small, and standard across the industry. It must be
written into the club's operational documentation.

**Decide by:** Phase 2 design review — the club must accept it in writing.
**Owner:** product + the pilot club's matchday manager.

---

## Q6 — Scanner as a PWA on iOS

**Risk.** The brief requires a PWA. Camera access from an *installed* iOS PWA has
a history of breaking across Safari releases, and stadium staff devices are
frequently older iPhones on outdated iOS.

**Recommendation.** Build the PWA. Additionally:
1. Support running in a normal Safari tab, where `getUserMedia` is more reliable.
2. Support an external Bluetooth/USB HID barcode scanner as a keyboard-input
   fallback — many clubs already own these, and they are faster than a camera.
3. Buy the pilot club's actual device models during Phase 1 and test on them
   before writing scanner code.

If iOS proves unreliable on the club's hardware, the escape hatch is a thin
Capacitor wrapper around the same React application — not a rewrite.

**Decide by:** Phase 2 week 1, on real hardware. **Owner:** engineering.

---

## Q7 — Right to erasure vs financial and consent retention

**Tension.** The brief requires an account deletion/anonymisation workflow *and*
immutable financial history. A literal reading of "delete my data" conflicts with
tax law (7–10 year retention) and with the requirement to retain proof of
consent.

**Resolution.** Pseudonymisation, not deletion. Identity lives in `person`;
everything else references it. Erasure overwrites identity fields and severs the
link everywhere at once, while orders, payments and consent records survive under
GDPR Art. 17(3)(b)/(e) — legal obligation and legal claims. Detail in
[03 §21](03-data-model.md#21-deletion-and-retention-behaviour).

**What this means in practice:** a fan's erasure request leaves an invoice
showing a name, because tax law requires the invoice. This must be stated plainly
in the privacy policy, and the erasure confirmation email must say what was
retained and why. Users accept this when told; they do not accept discovering it.

**Decide by:** Phase 1 (the erasure workflow ships in Phase 1).
**Owner:** DPO / legal.

---

## Q8 — Stripe connected account: tenant or club level?

**Tension.** The brief puts billing at the tenant level, but a tenant may hold
multiple clubs which may be separate legal entities with separate bank accounts,
VAT numbers and boards.

**Recommendation.** Connected account at **club** level. A tenant with one club —
the common case — sees no difference. A tenant with two clubs gets correct
settlement without a manual reconciliation process we would otherwise have to
invent. Our SaaS subscription stays at tenant level.

This is already reflected in the model (`connected_account.club_id`) but is
called out because it contradicts a natural reading of "billing is per tenant".

**Decide by:** Phase 2 start. **Owner:** product.

---

## Q9 — Phase 1 scope is large

**Observation, not an objection.** Phase 1 as specified includes multi-tenancy,
auth, RBAC, club, teams, staff, players, academy, guardians, training,
attendance, public website, CMS, super admin *and* SaaS billing. At 4 engineers
that is 10–14 weeks after a 3–4 week foundation — roughly **4 months to first
production use**.

I have not reduced it. But two things should be understood:

- **SaaS billing in Phase 1 is only justified if we charge the pilot club from
  day one.** If the pilot is free or invoiced manually, moving billing to Phase 2
  buys ~3 weeks for the features the club actually feels.
- **CMS + public website is roughly a third of Phase 1.** It is also the most
  visible part to the club's board, which is often what secures the contract.
  Worth keeping for commercial reasons even though the academy features are the
  ones that create daily value.

**Decide by:** before Phase 1 planning. **Owner:** founder.

---

## Q10 — Keycloak at fan scale

**Risk.** ~2.5 M users in one realm by year 3. Workable, but admin-console user
search degrades badly and realm export stops being a viable backup mechanism.

**Mitigation, already in the design.** Our admin UI never proxies Keycloak user
search — it searches `person`, which is ours and properly indexed. Backups are
database-level. If it becomes a real problem, fan authentication moves to a
separate realm or cluster while staff stay put, because `user_account` is the
join key rather than the realm.

**Decide by:** not blocking. Monitor from 500 k users.

---

## Q11 — `person` is tenant-scoped, so a fan of two clubs is two records

**Consequence worth stating explicitly.** A supporter of two clubs held by
different tenants has one login and two `person` records. Cross-tenant fan
analytics ("how many of our fans also support X?") is therefore impossible by
design.

This is correct — each tenant is an independent data controller, and merging
would mean one club's data controls another's. But it will be asked for, and the
answer needs to be "no, deliberately", not a bug report.

---

## Q13 — Celery deferred to Phase 1 (deviation, already taken)

**What changed.** The architecture commits to Celery for background work
([00 §5](00-overview.md)). Phase 0 ships the outbox relay as a standalone async
process (`app/events/runner.py`) and runs its two periodic jobs — outbox
cleanup and audit partition creation — on timers inside it. There is no Celery,
no beat, no broker.

**Why.** Celery earns its keep when there is a real task workload: email, SMS,
wallet passes, report generation, image processing. All of that arrives in
Phase 1. Today the only asynchronous work is dispatching the outbox, which
needs a long-lived async process rather than a task queue, plus two timers.
Introducing Celery now would mean operating a worker and a scheduler to run two
cron-like jobs, and bridging sync Celery tasks onto async SQLAlchemy — real
machinery with no current payload.

**Why this is not a silent change.** The relay is a *separate deployable*, so
Celery slots in beside it rather than through it. Nothing in the codebase
assumes the relay is the only background process, and no handler signature
changes when Celery arrives.

**Decide by:** Phase 1, when the first notification is built. If the answer is
"Celery was never needed", that becomes an ADR superseding the mention in
[00 §5](00-overview.md). **Owner:** engineering.

---

## Q12 — Anthropometric data in the player profile

**Minor but real.** The brief places height and weight on the player profile.
Under GDPR these are health-adjacent for minors, and several national football
associations treat academy anthropometric tracking as sensitive.

**Recommendation.** Keep current height/weight on `player` (needed for kit and
squad lists) but put *longitudinal growth tracking* — the thing that is actually
sensitive, and a genuine safeguarding concern in youth football — in the medical
schema behind medical permissions.

**Decide by:** Phase 3. **Owner:** DPO + academy director.
