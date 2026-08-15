# 03 — Initial PostgreSQL Entity Model

This is the reference model. It covers the full product vision so that later
phases add tables rather than reshaping existing ones. Tables marked
**[Phase N]** are not created until that phase — but the shape they will take is
settled now, because that is what prevents the Phase-2 migration from breaking
Phase-1 data.

## 0. Conventions

| Rule | Value |
| --- | --- |
| Naming | `snake_case`, singular table names (`player`, not `players`) |
| Primary keys | `uuid` (UUIDv7, generated in the application) |
| Tenant column | `tenant_id uuid NOT NULL` on every tenant-scoped table |
| Timestamps | `timestamptz`, always UTC. `created_at`, `updated_at` |
| Attribution | `created_by uuid` on auditable business entities |
| Money | `*_minor bigint NOT NULL` + `currency char(3) NOT NULL`. Never `numeric`, never float. |
| Percentages | basis points, `int` (`250` = 2.50 %) |
| Soft delete | `deleted_at timestamptz` only where restore is a real requirement; otherwise hard delete or state field |
| Enums | PostgreSQL `text` + `CHECK` constraint, not native enum types (native enums make additive migrations painful) |
| FKs | Always declared. `ON DELETE RESTRICT` by default; `CASCADE` only for owned child rows |
| Composite FKs | Tenant-scoped FKs include `tenant_id` (see §1.2) |

### 0.1 Why composite tenant foreign keys

Every FK between two tenant-scoped tables is declared as a composite:

```sql
FOREIGN KEY (tenant_id, team_id) REFERENCES team (tenant_id, id)
```

which requires `UNIQUE (tenant_id, id)` on the parent. This costs one extra
index per table and makes it **structurally impossible** to attach a row in
tenant A to a parent in tenant B — even if application code and RLS both fail.
This is the third and strongest layer of the isolation defence described in
[04](04-multitenancy.md).

---

## 1. Platform & tenancy

```
tenant
  id, slug UNIQUE, legal_name, trading_name,
  country_code char(2), default_locale, supported_locales text[],
  default_currency char(3), timezone, date_format,
  status (PENDING|ACTIVE|SUSPENDED|CLOSED), suspended_reason,
  vat_number, billing_email, legal_address jsonb,
  created_at, updated_at
  UNIQUE (id)                            -- for composite FKs

tenant_setting                            -- typed key/value, avoids column sprawl
  tenant_id, key, value jsonb, updated_at, updated_by
  PK (tenant_id, key)

club
  id, tenant_id, slug, legal_name, display_name, short_name (max 8), 
  founded_year, country_code, default_locale, supported_locales text[],
  currency char(3), timezone, status, primary_venue_id,
  crest_media_id, created_at, updated_at
  UNIQUE (tenant_id, slug), UNIQUE (tenant_id, id)

club_branding
  club_id PK, logo_light_media_id, logo_dark_media_id, favicon_media_id,
  color_primary, color_secondary, color_accent,     -- validated hex, contrast-checked
  social jsonb, updated_at, updated_by

club_domain
  id, tenant_id, club_id, hostname CITEXT UNIQUE,
  kind (PRIMARY|ALIAS), verification_token, verification_status,
  tls_status, verified_at, created_at
  -- hostname is globally unique: it is the tenant-resolution key for public-web

department                                -- optional org structure inside a club
  id, tenant_id, club_id, parent_id, name, created_at

season
  id, tenant_id, club_id, name, start_date, end_date, is_current bool,
  UNIQUE (tenant_id, club_id, name)
  -- partial unique: only one current season per club
  UNIQUE (club_id) WHERE is_current

facility
  id, tenant_id, club_id, name, kind (PITCH|GYM|CLASSROOM|MEDICAL|OTHER),
  surface, address jsonb, capacity, is_active
```

**Design note — season scoping.** Seasons sit on the club, not the tenant, because
a tenant may hold clubs in different countries with different season calendars
(e.g. a Nordic summer league and a continental winter league). Cost: a tenant with
two clubs maintains two season records. Accepted.

---

## 2. People & identity

The `User` / `Person` split is load-bearing; see [05](05-identity-and-authentication.md).

```
user_account                              -- authentication identity, NOT tenant-scoped
  id, subject_id text UNIQUE,             -- Keycloak `sub`
  email CITEXT UNIQUE, email_verified,
  status (ACTIVE|LOCKED|DISABLED), mfa_enabled, mfa_required,
  is_platform_user bool DEFAULT false,
  last_login_at, created_at

person                                    -- a human, within one tenant
  id, tenant_id, user_id NULL,            -- linked once they have a login
  first_name, last_name, display_name,
  birth_date date NULL, gender NULL, nationality char(2)[],
  email CITEXT NULL, phone NULL, address jsonb NULL,
  preferred_locale, 
  is_minor_cached bool,                   -- derived from birth_date, refreshed nightly
  source (STAFF_ENTRY|SELF_REGISTRATION|IMPORT|DEMO),
  anonymized_at NULL,
  created_at, updated_at, created_by
  UNIQUE (tenant_id, user_id) WHERE user_id IS NOT NULL
  UNIQUE (tenant_id, id)
  INDEX (tenant_id, lower(last_name), lower(first_name))
  INDEX using gin (tenant_id, to_tsvector('simple', display_name))

person_role_flag                          -- fast "what is this person to us" lookup
  tenant_id, person_id, role_kind (PLAYER|STAFF|GUARDIAN|FAN|MEMBER|PROSPECT),
  first_seen_at, is_active
  PK (tenant_id, person_id, role_kind)
```

**Why `person` is tenant-scoped.** The alternative — one global person shared
across tenants — would mean Club A's edits to a shared record affect Club B, and
GDPR erasure requests would span controllers. Each tenant is an independent data
controller; each therefore holds its own `person` rows. A supporter of two clubs
in two tenants is two `person` rows and one `user_account`. That is legally
correct and operationally simpler.

`person_role_flag` exists because "is this person a player?" is asked on nearly
every screen and must not require six LEFT JOINs.

---

## 3. Authorization

```
permission                                -- static, seeded from code
  key PK,                                 -- e.g. 'ticketing.price.update'
  module, description, 
  scope_levels text[],                    -- which scopes it can be granted at
  is_sensitive bool                       -- forces audit + second-factor freshness

role
  id, tenant_id NULL,                     -- NULL = system template
  key, name, description,
  scope_level (PLATFORM|TENANT|CLUB|TEAM),
  is_system bool, is_assignable bool,
  UNIQUE (tenant_id, key)  -- NULLS NOT DISTINCT so system keys are globally unique

role_permission
  role_id, permission_key
  PK (role_id, permission_key)

role_assignment
  id, user_id, tenant_id NULL,            -- NULL only for platform roles
  club_id NULL, team_id NULL,             -- narrowing scope
  role_id, 
  valid_from, valid_until NULL,
  granted_by, granted_at, revoked_at NULL, revoke_reason
  INDEX (user_id, tenant_id) WHERE revoked_at IS NULL
  CHECK (scope narrowing is consistent with role.scope_level)
```

Roles are **data, not code**. Tenants may clone a system template and adjust it.
Business logic never reads a role name — only permission keys. See
[06](06-authorization.md).

---

## 4. Staff

```
staff_profile
  id, tenant_id, club_id, person_id, department_id NULL,
  job_title, employment_type, 
  start_date, end_date NULL, status (ACTIVE|ON_LEAVE|ENDED),
  is_coach bool, created_at
  UNIQUE (tenant_id, club_id, person_id) WHERE status <> 'ENDED'

staff_qualification
  id, tenant_id, staff_profile_id,
  kind (COACHING_LICENCE|FIRST_AID|SAFEGUARDING|DBS_CHECK|OTHER),
  identifier, issuing_body, issued_on, expires_on NULL,
  document_media_id NULL, verified_by NULL, verified_at NULL
  INDEX (tenant_id, expires_on) WHERE expires_on IS NOT NULL
```

The expiry index drives the "3 licences expiring" dashboard block and a nightly
job that emits `QualificationExpiring` at 60/30/7 days.

---

## 5. Teams, players, guardians

```
team
  id, tenant_id, club_id, name, code,
  gender (MALE|FEMALE|MIXED), age_group,       -- 'U15', 'SENIOR', free-form per country
  level (FIRST|RESERVE|YOUTH|FUTSAL|OTHER), is_academy bool,
  head_coach_staff_id NULL, status, created_at
  UNIQUE (tenant_id, club_id, code)
  UNIQUE (tenant_id, id)

team_season                               -- a team's participation in a season
  id, tenant_id, team_id, season_id, name_override, status
  UNIQUE (team_id, season_id)

player
  id, tenant_id, club_id, person_id,
  status (TRIAL|REGISTERED|LOANED_OUT|INACTIVE|DEPARTED),
  primary_position, secondary_positions text[], preferred_foot,
  federation_id,                          -- national FA registration number
  joined_club_on, left_club_on NULL,
  created_at, updated_at
  UNIQUE (tenant_id, club_id, person_id)
  UNIQUE (tenant_id, id)

player_registration                       -- player ↔ team ↔ season, with history
  id, tenant_id, player_id, team_id, season_id,
  shirt_number smallint NULL, kind (PERMANENT|LOAN|DUAL|TRIAL),
  registered_on, ended_on NULL, ended_reason,
  UNIQUE (team_id, season_id, shirt_number) WHERE ended_on IS NULL AND shirt_number IS NOT NULL
  UNIQUE (player_id, team_id, season_id) WHERE ended_on IS NULL
  INDEX (tenant_id, team_id, season_id) WHERE ended_on IS NULL

player_document
  id, tenant_id, player_id, kind (ID|PASSPORT|CONSENT|MEDICAL_CERT|PHOTO|CONTRACT|OTHER),
  media_id, issued_on, expires_on NULL, verified_by, verified_at,
  INDEX (tenant_id, expires_on) WHERE expires_on IS NOT NULL

guardian_relationship
  id, tenant_id, minor_person_id, guardian_person_id,
  relationship (MOTHER|FATHER|LEGAL_GUARDIAN|OTHER),
  is_primary bool, has_legal_custody bool,
  may_receive_communications bool, may_collect bool,
  may_view_development bool,              -- club policy, per relationship
  starts_on, ends_on NULL,
  UNIQUE (minor_person_id, guardian_person_id) WHERE ends_on IS NULL
  INDEX (tenant_id, guardian_person_id)
```

**Note.** `player.person_id` — not duplicated name/DOB fields. A person who is a
player *and* a supporter *and* later a coach is one `person` with three
attachments. This is the single most important modelling decision in the sporting
domain and it is why "Fan 360" can include "this fan is also a parent of two
academy players" without any reconciliation logic.

---

## 6. Consent & privacy

```
consent_policy
  id, tenant_id NULL,                     -- NULL = platform default
  key (TERMS|PRIVACY|MARKETING_EMAIL|MARKETING_SMS|PHOTO_MEDIA|DATA_PROCESSING|MEDICAL_SHARING),
  country_code NULL,                      -- country-specific variant
  version, effective_from, text_media_id, requires_guardian_below_age smallint NULL,
  UNIQUE (tenant_id, key, country_code, version)

consent_record                            -- append-only
  id, tenant_id, person_id, policy_id, policy_version,
  granted bool, 
  granted_by_person_id,                   -- self, or the guardian who consented
  basis (SELF|GUARDIAN|LEGITIMATE_INTEREST|CONTRACT),
  occurred_at, source (WEB|ADMIN|IMPORT|API), 
  ip_hash, user_agent_hash
  INDEX (tenant_id, person_id, policy_id, occurred_at DESC)

-- Current consent state is a view over the latest record per (person, policy).
-- Never a mutable column: withdrawal history is itself legally required.

privacy_request
  id, tenant_id, person_id, kind (EXPORT|ERASURE|RECTIFICATION|RESTRICTION),
  status (RECEIVED|VERIFYING|IN_PROGRESS|COMPLETED|REJECTED),
  requested_at, due_at,                   -- +30 days, drives an SLA dashboard
  completed_at, method (ANONYMIZE|DELETE), 
  retention_holds jsonb,                  -- what could not be erased and why
  handled_by, notes
```

`requires_guardian_below_age` is per policy per country — the reason we never
hardcode 16 (GDPR Art. 8 lets member states set 13–16, and it is 16 in Germany,
13 in Denmark and 14 in Italy/Spain).

---

## 7. Medical — separate PostgreSQL schema

Lives in schema `medical`, not `public`. The application uses a **separate
database role and connection pool** for it, granted only to requests carrying a
medical permission. A SQL-injection or ORM bug in the ticketing module therefore
cannot read a diagnosis, because the connection it holds has no privileges on
that schema. See [06 §5](06-authorization.md).

```
medical.medical_record
  id, tenant_id, player_id, opened_at, closed_at, notes_encrypted

medical.injury
  id, tenant_id, player_id, occurred_on, reported_by_staff_id,
  body_area, laterality, mechanism, diagnosis_code, diagnosis_text,
  severity, expected_return_on, actual_return_on, status

medical.treatment
  id, tenant_id, injury_id, performed_on, kind, notes, practitioner_staff_id

medical.rehab_plan / medical.rehab_session / medical.return_to_play_clearance
  ...

-- Coach-visible projection, in the PUBLIC schema, written only by medical services:
player_availability
  id, tenant_id, player_id,
  status (AVAILABLE|LIMITED|UNAVAILABLE),
  effective_from, effective_to NULL,
  limitation_note NULL,                   -- "no contact training" — never a diagnosis
  set_by_staff_id, created_at
  INDEX (tenant_id, player_id, effective_from DESC)
```

A coach selecting a squad reads `player_availability`. There is no join path from
their session to `medical.*` at all.

---

## 8. Training & attendance

```
drill
  id, tenant_id, club_id, title, category, description,
  duration_minutes, players_min, players_max, space, equipment text[],
  diagram_media_id, video_media_id, tags text[], age_groups text[],
  created_by, is_club_methodology bool

training_session
  id, tenant_id, club_id, team_id, season_id,
  starts_at timestamptz, duration_minutes, facility_id NULL, location_note,
  theme, objectives text,
  status (PLANNED|CONFIRMED|COMPLETED|CANCELLED), cancel_reason,
  mesocycle_id NULL,                      -- [Phase 3]
  created_by, created_at
  INDEX (tenant_id, team_id, starts_at)
  INDEX (tenant_id, starts_at) WHERE status IN ('PLANNED','CONFIRMED')

training_session_staff  (session_id, staff_profile_id, role)
training_session_drill  (id, session_id, drill_id, position smallint, duration_minutes, notes)

training_attendance
  id, tenant_id, session_id, player_id,
  status (INVITED|CONFIRMED|DECLINED|PRESENT|LATE|ABSENT|EXCUSED|UNAVAILABLE),
  minutes NULL, rpe smallint NULL,        -- 1–10, optional
  note, recorded_by, recorded_at
  UNIQUE (session_id, player_id)
  INDEX (tenant_id, player_id, recorded_at DESC)

-- [Phase 3] periodisation
macrocycle (id, tenant_id, team_id, season_id, name, start_date, end_date, goals)
mesocycle  (id, tenant_id, macrocycle_id, name, start_date, end_date, focus, load_target)
```

Attendance percentage is computed, never stored. At 500 players × 4 sessions/week
× 40 weeks = 80 000 rows/season/club — trivially aggregatable, and a stored
percentage would be wrong the moment a coach corrects a record.

---

## 9. Player development

```
evaluation_framework
  id, tenant_id, club_id, name, description,
  applies_to_age_groups text[], scale_hint,
  version smallint, status (DRAFT|ACTIVE|ARCHIVED), 
  UNIQUE (tenant_id, club_id, name, version)

evaluation_category  (id, framework_id, key, name, position smallint, weight_bp)
evaluation_metric
  id, category_id, key, name, description,
  scale_type (NUMERIC|LIKERT|ENUM|BOOLEAN|TEXT),
  scale_min, scale_max, options jsonb, weight_bp, is_required

evaluation
  id, tenant_id, player_id, framework_id, framework_version,
  team_id, season_id, evaluator_staff_id,
  period_start, period_end,
  status (DRAFT|SUBMITTED|SHARED_WITH_PLAYER|SHARED_WITH_GUARDIAN|ARCHIVED),
  overall_note, submitted_at, created_at
  INDEX (tenant_id, player_id, period_end DESC)

evaluation_score
  evaluation_id, metric_id, numeric_value numeric(6,2) NULL, text_value NULL, option_key NULL
  PK (evaluation_id, metric_id)

development_cycle
  id, tenant_id, player_id, title, start_date, end_date,
  owner_staff_id, status (ACTIVE|COMPLETED|ABANDONED),
  guardian_visible bool, player_visible bool

development_goal
  id, tenant_id, cycle_id, title, description, category,
  target_date, status (NOT_STARTED|IN_PROGRESS|ACHIEVED|MISSED|DROPPED),
  progress_bp int, position smallint

development_note
  id, tenant_id, cycle_id NULL, goal_id NULL, player_id,
  author_user_id, body,
  visibility (STAFF_ONLY|PLAYER|GUARDIAN), created_at
```

Frameworks are versioned and evaluations pin `framework_version`, so historic
evaluations remain interpretable after an academy director changes the metrics —
a requirement that is very hard to retrofit.

---

## 10. Competitions & matches

```
competition
  id, tenant_id, club_id, name, kind (LEAGUE|CUP|FRIENDLY|TOURNAMENT),
  governing_body, country_code, external_ref

competition_season
  id, tenant_id, competition_id, season_id, name, format jsonb

fixture
  id, tenant_id, club_id, competition_season_id NULL, team_id,
  opponent_name, opponent_club_id NULL, opponent_crest_media_id NULL,
  is_home bool, venue_id NULL,
  kickoff_at timestamptz, timezone,       -- stored tz for display fidelity
  status (SCHEDULED|POSTPONED|LIVE|FINISHED|ABANDONED|CANCELLED),
  score_home smallint, score_away smallint,
  reported_attendance int, 
  is_ticketed bool, notes
  INDEX (tenant_id, club_id, kickoff_at)
  INDEX (tenant_id, team_id, kickoff_at DESC)

match_squad
  id, tenant_id, fixture_id, player_id,
  role (STARTER|SUBSTITUTE|UNUSED_SUB|ABSENT), shirt_number, position,
  UNIQUE (fixture_id, player_id)

match_event
  id, tenant_id, fixture_id, minute smallint, added_time smallint,
  kind (GOAL|OWN_GOAL|ASSIST|YELLOW|SECOND_YELLOW|RED|SUB_IN|SUB_OUT|PENALTY_SCORED|
        PENALTY_MISSED|INJURY|OTHER),
  side (HOME|AWAY), player_id NULL, related_player_id NULL,
  detail jsonb, recorded_by, recorded_at
  INDEX (fixture_id, minute)

match_player_stat                         -- derived from events, rebuildable
  fixture_id, player_id, minutes, goals, assists, yellows, reds, 
  PK (fixture_id, player_id)
```

`match_player_stat` is a materialised projection rebuilt from `match_event` — the
authoritative record is the event stream, so a corrected event re-derives stats.

---

## 11. Venues & seating

Supports general admission and assigned seating from day one, as required.

```
venue
  id, tenant_id, club_id NULL, name, address jsonb, timezone, 
  total_capacity, map_media_id

venue_stand    (id, tenant_id, venue_id, name, code, position smallint)
venue_section
  id, tenant_id, venue_id, stand_id, name, code,
  admission (GENERAL|ASSIGNED),
  ga_capacity int NULL,                   -- required when admission = GENERAL
  is_accessible, is_away, is_hospitality,
  CHECK ((admission = 'GENERAL') = (ga_capacity IS NOT NULL))
  UNIQUE (venue_id, code)

venue_row  (id, tenant_id, section_id, label, position smallint)
seat
  id, tenant_id, venue_id, section_id, row_id, label,
  kind (STANDARD|WHEELCHAIR|COMPANION|RESTRICTED_VIEW|HOSPITALITY),
  x numeric, y numeric,                   -- for the seat map UI, added later
  status (ACTIVE|BLOCKED|REMOVED),
  UNIQUE (section_id, row_id, label)
  UNIQUE (tenant_id, id)

gate  (id, tenant_id, venue_id, code, name, is_active)
gate_section_access  (gate_id, section_id)   -- which gates admit which sections
```

---

## 12. Ticketing

```
ticketed_event                            -- a sellable event; usually but not always a fixture
  id, tenant_id, club_id, venue_id, fixture_id NULL,
  title, starts_at, doors_open_at, 
  access_opens_at, access_closes_at,      -- scanner validity window
  status (DRAFT|ON_SALE|PAUSED|CLOSED|CANCELLED),
  currency char(3), sales_open_at, sales_close_at,
  max_tickets_per_order smallint,
  UNIQUE (tenant_id, id)

price_category  (id, tenant_id, club_id, key, name, position)   -- ADULT|CHILD|SENIOR|…

ticket_type
  id, tenant_id, ticketed_event_id, section_id NULL, price_category_id,
  name, price_minor bigint, currency, 
  quantity_total int NULL,                -- NULL = bounded by section capacity
  quantity_sold int NOT NULL DEFAULT 0,
  quantity_held int NOT NULL DEFAULT 0,
  sales_start, sales_end,
  requires_membership_plan_id NULL, member_discount_bp int,
  min_per_order, max_per_order,
  CHECK (quantity_total IS NULL OR quantity_sold + quantity_held <= quantity_total)

seat_inventory                            -- one row per seat per event (assigned seating)
  id, tenant_id, ticketed_event_id, seat_id, ticket_type_id NULL,
  status (AVAILABLE|HELD|SOLD|BLOCKED|SEASON_TICKET),
  hold_id NULL, hold_expires_at NULL,
  UNIQUE (ticketed_event_id, seat_id)
  INDEX (ticketed_event_id, status) WHERE status = 'AVAILABLE'
  INDEX (hold_expires_at) WHERE status = 'HELD'

inventory_hold
  id, tenant_id, ticketed_event_id, cart_id, 
  created_at, expires_at, released_at NULL, release_reason
```

### 12.1 Overselling — where the guarantee actually lives

Redis is used for UX responsiveness (fast "is this seat free" reads, seat-map
broadcast). **It is never the authority.** The guarantees are:

- *Assigned seating*: `UNIQUE (ticketed_event_id, seat_id)` plus a conditional
  update. Taking a seat is
  `UPDATE seat_inventory SET status='HELD', hold_id=…, hold_expires_at=…
   WHERE ticketed_event_id=… AND seat_id=… AND (status='AVAILABLE'
   OR (status='HELD' AND hold_expires_at < now()))` — success is `rowcount = 1`.
  Two concurrent buyers: one gets the row, the other gets zero and a clean
  `SeatUnavailable`.
- *General admission*: the `CHECK` above plus
  `UPDATE ticket_type SET quantity_held = quantity_held + :n
   WHERE id=… AND (quantity_total IS NULL OR quantity_total - quantity_sold - quantity_held >= :n)`.
  Atomic, no read-modify-write, no application-level locking.
- Expired holds are swept by a Celery beat job every 30 s, **and** treated as
  free by the conditional update above — so a stalled sweeper cannot freeze
  inventory.

This is deliberately boring. Ticket overselling is the failure mode most likely
to end a pilot, and cleverness here has no upside.

### 12.2 Ticket and credential

```
ticket
  id, tenant_id, club_id, ticketed_event_id,
  order_line_id NULL,                     -- NULL for comps
  ticket_type_id, price_category_id,
  section_id, seat_id NULL,
  holder_person_id NULL,                  -- NULL for unnamed GA tickets
  season_ticket_id NULL,                  -- generated from a season ticket
  state (CREATED|ISSUED|ACTIVE|SCANNED|TRANSFERRED|RESOLD|REFUNDED|REVOKED|CANCELLED),
  state_changed_at,
  price_paid_minor, currency,
  serial text,                            -- human-readable, printed on the ticket
  created_at
  UNIQUE (tenant_id, ticketed_event_id, serial)
  INDEX (tenant_id, holder_person_id, created_at DESC)
  INDEX (ticketed_event_id, state)
  UNIQUE (ticketed_event_id, seat_id) WHERE state NOT IN ('CANCELLED','REFUNDED','TRANSFERRED','RESOLD')

ticket_state_transition                   -- append-only
  id, tenant_id, ticket_id, from_state, to_state, reason,
  actor_user_id NULL, actor_kind (USER|SYSTEM|SCANNER), occurred_at, metadata jsonb

access_credential
  id, tenant_id, ticket_id,
  kind (QR_STATIC|QR_ROTATING|APPLE_WALLET|GOOGLE_WALLET|NFC|PRINTED),
  credential_ref text UNIQUE,             -- opaque, what the QR actually carries
  key_id text,                            -- signing key version, for rotation
  status (ACTIVE|SUPERSEDED|REVOKED), supersedes_id NULL,
  issued_at, revoked_at, revoke_reason,
  wallet_pass_ref NULL, device_binding NULL
  INDEX (tenant_id, ticket_id)

ticket_scan                               -- append-only, partitioned monthly
  id, tenant_id, ticketed_event_id, credential_id NULL, ticket_id NULL,
  person_id NULL, gate_id NULL, device_id, operator_user_id,
  result (VALID|ALREADY_USED|WRONG_EVENT|WRONG_GATE|OUTSIDE_WINDOW|REVOKED|
          INVALID_SIGNATURE|UNKNOWN|CANCELLED),
  scanned_at, client_scanned_at, was_offline bool, sync_batch_id NULL,
  raw_payload_hash
  -- THE admission guarantee:
  UNIQUE (credential_id) WHERE result = 'VALID'
  INDEX (tenant_id, ticketed_event_id, scanned_at)

scanner_device
  id, tenant_id, club_id, label, device_key_hash,
  registered_by, registered_at, last_seen_at, status (ACTIVE|REVOKED)

ticket_transfer                                                        -- [Phase 4]
  id, tenant_id, ticket_id, from_person_id, to_email CITEXT, to_person_id NULL,
  token_hash, status (PENDING|ACCEPTED|DECLINED|CANCELLED|EXPIRED),
  initiated_at, expires_at, accepted_at

resale_listing / resale_sale                                           -- [Phase 4]
```

`UNIQUE (credential_id) WHERE result = 'VALID'` is the whole single-admission
guarantee, expressed in one line the database enforces. A duplicate scan attempts
an insert, violates the constraint, and the service converts that into
`ALREADY_USED` — which it then records as a *separate, non-VALID* scan row so the
audit trail keeps both events. No application-level locking, correct under any
concurrency, correct across replicas.

Separating `ticket` from `access_credential` means a ticket transfer revokes a
credential and issues a new one while ownership history stays on the ticket, and
means Apple Wallet can be added in Phase 4 without touching the ticket table.

---

## 13. Season tickets & memberships

```
season_ticket_product
  id, tenant_id, club_id, season_id, name, description,
  section_id NULL, price_category_id, price_minor, currency,
  included_competition_ids uuid[], excluded_fixture_ids uuid[],
  status, sales_start, sales_end, renewal_opens_at, renewal_closes_at

season_ticket
  id, tenant_id, club_id, season_id, product_id,
  holder_person_id, seat_id NULL, card_serial,
  status (PENDING|ACTIVE|SUSPENDED|EXPIRED|CANCELLED),
  valid_from, valid_to, order_line_id, renewed_from_id NULL,
  UNIQUE (season_id, seat_id) WHERE status IN ('PENDING','ACTIVE')

membership_plan
  id, tenant_id, club_id, key, name, description,
  price_minor, currency, period (SEASON|MONTHLY|YEARLY),
  season_id NULL, capacity NULL, status, sort_order

membership_benefit
  id, plan_id, 
  kind (TICKET_DISCOUNT|SHOP_DISCOUNT|LOYALTY_MULTIPLIER|PRIORITY_WINDOW|
        FREE_TICKETS|EXCLUSIVE_CONTENT|EVENT_ACCESS|CUSTOM),
  config jsonb,                           -- {"percent_bp": 1000} etc.
  description_i18n jsonb

membership
  id, tenant_id, club_id, plan_id, member_person_id,
  member_number, status (PENDING|ACTIVE|EXPIRED|CANCELLED|REFUNDED),
  valid_from, valid_to, auto_renew, order_line_id, renewed_from_id NULL,
  UNIQUE (tenant_id, club_id, member_number)
  INDEX (tenant_id, member_person_id, valid_to DESC)
```

Benefits are rows with typed config, not columns and not code. Adding
"10 % off away travel" is a data change.

---

## 14. Fans & loyalty

```
fan_profile
  person_id PK, tenant_id, club_id NULL,
  favourite_player_id NULL, supporter_since,
  acquisition_source, tags text[],
  last_engaged_at

communication_preference
  tenant_id, person_id, channel (EMAIL|SMS|PUSH|POST), 
  topic (TRANSACTIONAL|NEWS|MATCHDAY|COMMERCIAL|ACADEMY|FUNDRAISING),
  opted_in bool, updated_at, source
  PK (tenant_id, person_id, channel, topic)

loyalty_program
  id, tenant_id, club_id, name, points_name, status,
  expiry_policy jsonb,                    -- {"kind":"ROLLING","months":24}
  earn_rules jsonb

loyalty_account
  id, tenant_id, program_id, person_id, tier_id NULL,
  balance_cached bigint, balance_as_of,   -- rebuildable cache, never authoritative
  UNIQUE (program_id, person_id)

loyalty_transaction                       -- append-only ledger
  id, tenant_id, account_id, delta bigint, 
  reason_code, source_kind, source_id,
  expires_at NULL, expired_from_id NULL,
  idempotency_key text UNIQUE, created_at
  INDEX (account_id, created_at DESC)

loyalty_tier    (id, program_id, name, min_points, benefits jsonb, position)
loyalty_reward  (id, program_id, name, cost_points, stock, per_person_limit, status)
loyalty_redemption (id, account_id, reward_id, transaction_id, status, fulfilled_at)
```

Balance is `SUM(delta)` over the ledger; `balance_cached` is an optimisation with
a rebuild job and a nightly consistency check that alerts on drift.

---

## 15. Ordering, commerce, fundraising

```
cart
  id, tenant_id, club_id, person_id NULL, session_token_hash,
  currency, status (OPEN|CHECKING_OUT|CONVERTED|ABANDONED|EXPIRED),
  expires_at, created_at
cart_line
  id, cart_id, line_type, reference_id, quantity, 
  reservation_ref NULL, unit_price_minor, metadata jsonb

"order"                                   -- quoted: ORDER is a SQL keyword
  id, tenant_id, club_id, order_number,
  person_id NULL, guest_email CITEXT NULL,
  channel (WEB|ADMIN|POS|API),
  status (PENDING|AWAITING_PAYMENT|PAID|PARTIALLY_REFUNDED|REFUNDED|CANCELLED|FAILED),
  currency, subtotal_minor, discount_minor, shipping_minor, tax_minor, total_minor,
  billing_address jsonb, shipping_address jsonb,
  discount_code_id NULL, placed_at, 
  idempotency_key text,
  UNIQUE (tenant_id, order_number)
  UNIQUE (tenant_id, idempotency_key)
  INDEX (tenant_id, person_id, placed_at DESC)

order_line
  id, tenant_id, order_id,
  line_type (TICKET|SEASON_TICKET|MEMBERSHIP|PRODUCT|DONATION|ACADEMY_FEE|FEE|SHIPPING),
  reference_id,                           -- polymorphic, resolved by the line handler
  description_snapshot text,              -- what the buyer saw
  snapshot jsonb,                         -- full product/price state at purchase
  unit_price_minor, quantity, discount_minor,
  tax_rate_bp, tax_minor, total_minor,
  fee_category,                           -- drives platform fee calculation
  UNIQUE (order_id, id)

order_refund
  id, tenant_id, order_id, amount_minor, currency, reason,
  status (REQUESTED|PROCESSING|COMPLETED|FAILED),
  payment_refund_id NULL, requested_by, created_at
order_refund_line (refund_id, order_line_id, amount_minor, quantity)
```

Nothing here is ever updated destructively. A price change tomorrow does not
alter what an order says today, because `snapshot` holds the state at purchase.
"Do not calculate historical totals using current product prices" is enforced by
there being no path from `order_line` to a live price.

```
product_category (id, tenant_id, club_id, parent_id, slug, position)
product
  id, tenant_id, club_id, slug, category_id, name, description,
  status (DRAFT|ACTIVE|ARCHIVED), tax_class, 
  base_price_minor, currency, requires_shipping, is_personalisable,
  UNIQUE (tenant_id, club_id, slug)
product_variant
  id, tenant_id, product_id, sku, option_values jsonb,   -- {"size":"L","print":"custom"}
  price_minor NULL, barcode, weight_grams, status,
  UNIQUE (tenant_id, sku)
inventory_item     (variant_id, location_id, on_hand int, reserved int,
                    CHECK (reserved >= 0 AND on_hand >= reserved))
inventory_movement (id, tenant_id, variant_id, location_id, delta, reason, ref, created_at)
discount_code
  id, tenant_id, club_id, code CITEXT, kind (PERCENT|FIXED|FREE_SHIPPING),
  value_bp/value_minor, usage_limit, used_count, per_person_limit,
  valid_from, valid_to, conditions jsonb,
  UNIQUE (tenant_id, club_id, code)
shipment / shipment_line / fulfilment_location

campaign
  id, tenant_id, club_id, slug, title, description, cover_media_id,
  goal_minor, currency, raised_cached_minor, donor_count_cached,
  starts_at, ends_at, visibility, beneficiary, 
  fiscal_treatment_key,                   -- jurisdiction config, NOT hardcoded "donation"
  status
donation
  id, tenant_id, campaign_id, order_line_id, donor_person_id NULL,
  amount_minor, currency, is_anonymous, public_message, 
  tax_receipt_ref NULL, created_at
```

`fiscal_treatment_key` points at a jurisdiction configuration that decides whether
a payment is legally a donation, a gift with consideration, or a plain sale, and
what wording and receipt is required. We do not assume any of it.

---

## 16. Payments

```
connected_account
  id, tenant_id, club_id, provider, provider_account_id,
  country char(2), default_currency,
  charges_enabled, payouts_enabled, onboarding_status,
  requirements jsonb, requirements_due_at, updated_at
  UNIQUE (provider, provider_account_id)

payment_intent
  id, tenant_id, club_id, order_id NULL, subscription_id NULL,
  provider, provider_ref, connected_account_id NULL,
  amount_minor, currency, 
  application_fee_minor,                  -- our platform fee, computed at creation
  status (REQUIRES_ACTION|PROCESSING|SUCCEEDED|FAILED|CANCELLED),
  failure_code, created_at, idempotency_key
  UNIQUE (provider, provider_ref)

payment
  id, tenant_id, intent_id, provider_ref, status,
  captured_at, method_brand, method_last4, method_country,
  amount_minor, currency

payment_refund
  id, tenant_id, payment_id, provider_ref, amount_minor,
  application_fee_refunded_minor, reason, status, created_by, created_at

provider_event                            -- webhook idempotency
  id, provider, provider_event_id text, type, payload jsonb,
  signature_verified bool, received_at,
  status (RECEIVED|PROCESSED|FAILED|IGNORED), attempts, last_error, processed_at
  UNIQUE (provider, provider_event_id)

payout  (id, tenant_id, club_id, provider_ref, amount_minor, currency,
         status, arrival_date, created_at)
```

No card data. Ever. Only brand/last4/country returned by the provider.

---

## 17. SaaS billing

```
feature
  key PK, name, module, kind (BOOLEAN|LIMIT|QUOTA), description, default_value

plan            (id, key UNIQUE, name, tier, status, is_public, sort_order)
plan_version    (id, plan_id, version, effective_from, notes, UNIQUE (plan_id, version))
plan_feature    (plan_version_id, feature_key, enabled bool, limit_value bigint NULL,
                 PK (plan_version_id, feature_key))
plan_price
  id, plan_version_id, currency, interval (MONTH|YEAR), amount_minor,
  provider_price_ref, UNIQUE (plan_version_id, currency, interval)

tenant_subscription
  id, tenant_id, plan_version_id, 
  status (TRIALING|ACTIVE|PAST_DUE|PAUSED|CANCELLED),
  current_period_start, current_period_end, trial_ends_at,
  cancel_at, cancelled_at, provider_subscription_ref, currency
  INDEX (tenant_id) WHERE status IN ('TRIALING','ACTIVE','PAST_DUE')

billing_policy                            -- the commercial contract with a tenant
  id, tenant_id, 
  model (SUBSCRIPTION|TRANSACTION_FEE|HYBRID|ENTERPRISE),
  currency, monthly_minor, yearly_minor,
  effective_from, effective_to NULL, contract_ref, created_by,
  EXCLUDE USING gist (tenant_id WITH =, daterange(effective_from, effective_to) WITH &&)

billing_fee_rule
  id, billing_policy_id,
  category (TICKET|SEASON_TICKET|MEMBERSHIP|SHOP|DONATION|ACADEMY_FEE|OTHER),
  percentage_bp int, fixed_minor bigint,
  min_fee_minor, max_fee_minor,
  UNIQUE (billing_policy_id, category)

entitlement                               -- per-tenant overrides on top of the plan
  id, tenant_id, feature_key, 
  source (PLAN|OVERRIDE|TRIAL|PROMO), enabled, limit_value,
  effective_from, effective_to, granted_by, reason
  
platform_fee_transaction                  -- our revenue ledger, append-only
  id, tenant_id, club_id, order_id, order_line_id NULL,
  category, gross_minor, fee_minor, currency,
  provider_fee_ref, occurred_at
  INDEX (tenant_id, occurred_at)

usage_record  (id, tenant_id, metric, value, period_start, period_end, recorded_at)
platform_invoice (mirrored from the provider for reporting)
```

The `EXCLUDE USING gist` constraint makes overlapping billing policies for one
tenant impossible — meaning "which fee applies to this order?" always has exactly
one answer, enforced by the database rather than by careful code.

---

## 18. CMS, media, sponsorship, notifications

```
content_item
  id, tenant_id, club_id, kind (ARTICLE|PAGE),
  category_id NULL, author_person_id, cover_media_id,
  status (DRAFT|IN_REVIEW|SCHEDULED|PUBLISHED|ARCHIVED),
  published_at, scheduled_for, is_pinned, 
  created_by, created_at, updated_at
  INDEX (tenant_id, club_id, status, published_at DESC)
  INDEX (scheduled_for) WHERE status = 'SCHEDULED'

content_translation
  id, tenant_id, club_id, content_item_id, locale,
  title, slug, excerpt, body jsonb,       -- structured blocks, not HTML soup
  seo_title, seo_description, og_media_id,
  status (DRAFT|READY), translated_by, updated_at
  UNIQUE (content_item_id, locale)
  UNIQUE (club_id, locale, slug)          -- club_id denormalised for this index

content_category / content_category_translation
navigation_menu  (id, tenant_id, club_id, key, name)
navigation_item  (id, menu_id, parent_id, position, label_i18n jsonb, 
                  target_kind (CONTENT|URL|ROUTE), target_ref, visibility_rule jsonb)
banner (id, tenant_id, club_id, placement, media_id, link, starts_at, ends_at, position)

media_asset
  id, tenant_id, club_id NULL, storage_key, bucket,
  mime_type, byte_size, width, height, duration_ms, checksum_sha256,
  visibility (PUBLIC|TENANT|RESTRICTED), 
  alt_text_i18n jsonb, credit,
  uploaded_by, created_at, variants jsonb    -- derived renditions
  INDEX (tenant_id, created_at DESC)

sponsor            (id, tenant_id, club_id, company_name, logo_media_id, 
                    logo_dark_media_id, website, tier, status)
sponsorship_contract (id, tenant_id, sponsor_id, starts_on, ends_on,
                      value_minor, currency, document_media_id, status)
sponsor_placement  (id, tenant_id, contract_id, placement (WEBSITE_HEADER|WEBSITE_FOOTER|
                    SHIRT|ACADEMY|STADIUM|MATCHDAY|NEWSLETTER), position, active_from, active_to)
sponsor_contact    (id, sponsor_id, person_id NULL, name, role, email, phone)

notification_template
  id, tenant_id NULL, key, channel, locale, subject, body, version, status
  UNIQUE (tenant_id, key, channel, locale, version)
notification
  id, tenant_id, recipient_person_id NULL, recipient_address_hash,
  channel, template_key, locale, payload jsonb,
  status (QUEUED|SENDING|SENT|DELIVERED|BOUNCED|FAILED|SUPPRESSED),
  suppressed_reason, provider_ref, dedupe_key text,
  scheduled_for, sent_at, attempts
  UNIQUE (tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL
```

---

## 19. Platform infrastructure tables

```
outbox_event
  id, tenant_id NULL, aggregate_type, aggregate_id,
  event_type, event_version smallint, payload jsonb,
  occurred_at, available_at, published_at NULL,
  attempts smallint, last_error, status (PENDING|PUBLISHED|FAILED|DEAD),
  trace_id, correlation_id
  INDEX (available_at, id) WHERE status = 'PENDING'

processed_event                           -- consumer-side idempotency
  handler_name, event_id, processed_at
  PK (handler_name, event_id)

audit_log                                 -- append-only, monthly partitions
  id, tenant_id NULL, club_id NULL,
  actor_user_id NULL, actor_kind (USER|SYSTEM|PLATFORM|SCANNER|API_KEY),
  impersonated_by_user_id NULL,
  action, object_type, object_id,
  before jsonb NULL, after jsonb NULL,    -- redacted through a field allow-list
  ip_inet inet, user_agent, request_id, occurred_at
  INDEX (tenant_id, occurred_at DESC)
  INDEX (tenant_id, object_type, object_id, occurred_at DESC)

impersonation_session
  id, platform_user_id, tenant_id, reason, ticket_ref,
  approved_by NULL, started_at, expires_at, ended_at, 
  actions_count, INDEX (tenant_id, started_at DESC)

idempotency_key
  key, tenant_id, endpoint, request_hash,
  status (IN_PROGRESS|COMPLETED), response_status, response_body jsonb,
  created_at, expires_at,
  PK (tenant_id, key, endpoint)

api_key  (id, tenant_id, club_id NULL, name, prefix, secret_hash, 
          scopes text[], last_used_at, expires_at, revoked_at)
```

`audit_log.before/after` pass through a per-object field allow-list so passwords,
tokens, card data and medical fields are never written even if a developer adds
them to a model later. The allow-list is code, unit-tested, and failing closed:
unknown fields are omitted rather than included.

---

## 20. Indexing and partitioning summary

| Table | Strategy |
| --- | --- |
| `audit_log` | Range partition by month; drop/archive per retention policy |
| `ticket_scan` | Range partition by month; hot partition is small and fast |
| `outbox_event` | Partial index on pending rows only; published rows deleted after 7 days |
| `loyalty_transaction` | Index `(account_id, created_at DESC)`; partition when > 100 M |
| `person` | GIN trigram on display name for admin search |
| `ticket` | `(ticketed_event_id, state)` for the matchday counters |
| `notification` | Partial index on `status = 'QUEUED'` |

Every tenant-scoped index is prefixed with `tenant_id` unless it is a global
lookup (e.g. `credential_ref`), so index scans are naturally tenant-local.

## 21. Deletion and retention behaviour

| Data | On erasure request |
| --- | --- |
| `person` identity fields | Overwritten with tombstone values, `anonymized_at` set |
| `user_account` | Deleted in Keycloak, row retained with `subject_id` nulled |
| `order`, `order_line`, `payment*` | **Retained.** Legal obligation (tax law, 7–10 y). `person_id` retained but resolves to an anonymised person |
| `ticket_scan` | Retained 24 months, then aggregated and rows dropped |
| `consent_record` | Retained — proof of consent is itself a legal requirement |
| `audit_log` | Retained per policy; actor fields pseudonymised |
| `training_attendance`, `evaluation` | Deleted or anonymised (no legal retention basis) |
| `medical.*` | Retained per national medical-record law (often longer than GDPR default) |

The mechanism is **pseudonymisation, not deletion**: identity lives in `person`,
and every other table references it. Anonymising one row severs the link
everywhere at once while leaving legally required financial records intact and
internally consistent. See [open questions](open-questions.md#q7) for the tension
this creates with a literal reading of "right to erasure".
