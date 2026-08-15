# 16 — Implementation Roadmap

The data model in [03](03-data-model.md) covers the full vision. Delivery does
not. Each phase below ends with something a real club can use in production.

Estimates assume **4 engineers** (2 backend, 1.5 frontend, 0.5 infrastructure)
plus a designer and a product owner. They are ranges, not commitments.

---

## Phase 0 — Foundation (3–4 weeks)

No product features. Everything after this is faster because of it, and slower
without it.

- Monorepo, tooling, CI pipeline, import-boundary contracts
- Docker Compose environment with all services, TLS, seeded Keycloak realm
- `core`: config, session/UoW, tenant context, `Money`, IDs, clock, errors,
  pagination, telemetry, storage port
- Tenancy: `tenant`, `club`, RLS policies and the migration pattern that applies
  them automatically to new tables
- Identity: Keycloak integration, `user_account`, `person`, token validation
- Authorization: permissions, roles, assignments, `Requires` dependency
- Entitlements: features, plans, resolution and caching
- Outbox + relay + Celery + `processed_event`
- Audit log writer with the field allow-list
- Design system tokens, primitives, `DataTable`, `PageHeader`, `FilterBar`,
  `EmptyState`, `ErrorState`
- `admin-web` shell: auth, navigation from permissions, club switcher, ⌘K
- The generated test suites: isolation, permission matrix, entitlement gating

**Exit criteria.** Two tenants exist. A user with a team-scoped role logs into
admin-web and sees only what they may see. The cross-tenant probe passes against
every route. An outbox event round-trips to a Celery handler. `docker compose up`
works from a clean clone on macOS and Linux.

---

## Phase 1 — Club Core (10–14 weeks)

The club can stop using spreadsheets.

| Area | Scope |
| --- | --- |
| Club | Clubs, departments, seasons, facilities, settings, branding |
| Staff | Profiles, qualifications, document expiry alerts |
| Teams | Teams, team-seasons, rosters |
| People & players | Person registry with dedup, player profiles, registrations, shirt numbers, documents |
| Guardians | Relationships, per-relationship permissions, consent capture |
| Academy | Age groups, registrations, fee *obligations* (recording only — see [08 §8](08-saas-billing.md)) |
| Training | Sessions, drill library, attendance, attendance reporting |
| Matches | Fixtures, squads, basic match events, minutes |
| CMS | Articles, pages, categories, media, navigation, scheduled publishing, translations, article types |
| Writing assistant | Improve-this-text and headline suggestions on one platform-held key, entitlement-gated and metered per tenant ([ADR-0011](../decisions/ADR-0011-ai-writing-assistant.md)) |
| Public web | Home, news, fixtures/results, teams, players, staff, contact, custom domain |
| Portal | Guardian portal: schedule, attendance, announcements, documents, consent |
| Super admin | Tenant CRUD, plans, entitlements, subscriptions, impersonation, health |
| SaaS billing | Stripe Billing, plans, subscriptions, dunning, platform dashboard |
| Notifications | Email channel, templates, preferences, the first six notification types |
| Privacy | Consent records, data export, erasure workflow |

**Exit criteria.** A pilot club runs its academy in production: 280 players, 11
teams, guardians logged in, attendance recorded weekly, public website live on
the club's own domain, and the club pays us by subscription.

**Deliberately deferred:** any fan payment, ticketing, shop, memberships,
evaluations, medical, scouting.

---

## Phase 2 — Revenue (12–16 weeks)

The club starts earning through the platform. Highest risk, highest value.

| Area | Scope |
| --- | --- |
| Fan accounts | Registration, fan profile, dashboard, communication preferences |
| Payments | Stripe Connect onboarding, direct charges, webhooks, refunds, payouts |
| Ordering | Cart, checkout, line handlers, price snapshots, tax lines, refunds |
| Venues | Stands, sections, rows, seats, gates |
| Ticketing | Ticketed events, ticket types, GA + assigned inventory, holds, purchase |
| Credentials | Signed QR credentials, issuance, revocation |
| Scanner | PWA, camera scanning, online validation, offline manifest + sync |
| Season tickets | Products, purchase, per-fixture ticket generation |
| Memberships | Plans, configurable benefits, purchase, renewal, discount application |
| Shop | Catalogue, variants, stock, cart, checkout, fulfilment, discount codes |
| Fundraising | Campaigns, donations, receipts |
| Platform fees | Billing policies, fee rules, fee ledger, reversal on refund |
| Academy fees | Online recurring collection on the connected account |
| Analytics | Sales, attendance, revenue reporting |

**Sequencing within the phase matters.** Payments → ordering → GA ticketing →
credentials → scanner must be built in that order and hardened before assigned
seating, memberships or shop start. Ticketing that oversells or a scanner that
fails at the turnstile ends the pilot; a missing shop does not.

**Exit criteria.** A full matchday runs on the platform: 4 000 tickets sold
online, scanned at four gates including a deliberate network outage, revenue
reconciled between our fee ledger and Stripe to the cent, refunds processed for a
postponed fixture with fees reversed.

---

## Phase 3 — Football Professional (10–12 weeks)

Depth for the sporting department.

- Evaluation frameworks (custom categories, metrics, scales, versioning)
- Evaluations with history and trend visualisation
- Individual development plans: cycles, goals, reviews, guardian visibility
- Training periodisation: macro/meso cycles, load planning
- Detailed match statistics and player minutes reporting
- Medical module: separate schema, separate role, injuries, treatments,
  rehabilitation, return-to-play, availability projection
- Scouting: prospects, reports, watchlists, assignments, recommendations
- Advanced analytics: academy retention, attendance correlation, development
  progression

**Exit criteria.** An academy director defines a club-specific evaluation
framework, runs a full review cycle across 11 teams, and shares outcomes with
players and guardians under the club's own visibility rules — with the medical
isolation test passing.

---

## Phase 4 — Fan Experience (10–12 weeks)

- Apple Wallet and Google Wallet passes
- Rotating QR credentials
- Ticket transfer
- Official resale with settlement
- Loyalty: ledger, tiers, campaigns, rewards, redemption
- Fan segmentation and campaign tooling
- SMS and push channels
- Sponsorship placements and reporting
- Attendance-driven fan 360 insight

---

## Cross-cutting, every phase

Not a phase, because these are never "done":

- Accessibility review before each release
- Security review before each release; external penetration test before Phase 2
  ships (it is the first phase that touches money)
- Performance testing against the phase's volume targets
- ADR written for every consequential decision
- Documentation updated in the same PR as the change that invalidates it

## Sequencing risks

| Risk | Mitigation |
| --- | --- |
| Stripe Connect onboarding blocks the pilot club for weeks | Start KYC onboarding at the beginning of Phase 2, not the end |
| Scanner fails on the club's actual devices | Buy the exact devices in Phase 1; test on them from the first week of Phase 2 |
| Seat map for a real stadium is harder than expected | Ship GA first; assigned seating is separately sequenced with real venue data imported early |
| Phase 1 scope creep from an enthusiastic pilot club | The phase table above is the contract; additions displace, they do not add |
| VAT configuration unresolved when Phase 2 ships | Decision needed before Phase 2 starts — see [open questions](open-questions.md#q4) |
