# 12 — API Conventions

## 1. Versioning and layout

```
/api/v1/…                     tenant-scoped staff + fan API
/api/v1/portal/…              player / guardian / member portal
/api/v1/public/…              unauthenticated, cacheable, powers public-web
/api/v1/platform/…            super-admin only
/api/v1/webhooks/{provider}   inbound, signature-verified, unauthenticated
/health  /health/ready  /metrics
```

`v1` is in the path. It changes only for genuinely breaking changes; additive
changes ship in place. When `v2` arrives, `v1` is supported for at least 12
months, and both are served by the same application with separate router
packages and shared services.

## 2. Resource naming

- Plural nouns: `/clubs`, `/players`, `/ticketed-events`
- Nesting only where the child cannot exist without the parent, and only one
  level deep: `/ticketed-events/{id}/ticket-types` ✓,
  `/clubs/{id}/teams/{id}/players/{id}/evaluations` ✗
- Deep relations are queried by filter instead:
  `/evaluations?player_id=…&season_id=…`
- Actions that are not CRUD get an explicit sub-resource verb:
  `POST /orders/{id}/refunds`, `POST /tickets/{id}/transfers`,
  `POST /ticketed-events/{id}/publish`. Not `POST /orders/{id}?action=refund`.
- `kebab-case` in paths, `snake_case` in JSON bodies (matching the backend and
  the database; the generated TS client is typed either way, so consistency with
  the server wins).

## 3. Pagination

Both styles, deliberately, because one does not fit both use cases:

**Cursor (default)** — for feeds, exports, large collections, anything the fan
site touches:

```
GET /players?limit=50&cursor=eyJpZCI6…
{ "data": [...], "page": { "next_cursor": "…", "has_more": true } }
```

**Offset (opt-in)** — for admin tables that need page numbers and total counts:

```
GET /players?limit=50&offset=200&with_total=true
{ "data": [...], "page": { "limit": 50, "offset": 200, "total": 284 } }
```

Rules that keep offset pagination from becoming a performance problem:

- `with_total` is opt-in; the count query is the expensive half and most screens
  do not need it.
- Above 10 000 rows the total is reported as an estimate from
  `pg_class.reltuples` with `"total_is_estimate": true`, and the UI renders
  "about 12,000". Exact counts on large tenant tables are not worth a sequential
  scan on every page load.
- `offset` is capped at 10 000. Beyond that the API returns
  `PAGINATION_LIMIT_EXCEEDED` and directs the caller to cursor mode. Deep offset
  paging is always either a bug or a scraper.

`limit` defaults to 25, maximum 100 (1 000 for explicit export endpoints).

## 4. Filtering, sorting, sparse fields

```
GET /players?team_id=…&status=REGISTERED&q=popescu
           &registered_after=2025-08-01
           &sort=-created_at,last_name
           &fields=id,display_name,team,status
```

- Filters are **explicit, typed query parameters declared per endpoint** — not a
  generic query language. A generic filter DSL over an ORM is an SQL-injection
  and performance incident waiting to happen, and it makes every endpoint's
  behaviour unbounded.
- Every filterable field must have an index. This is checked in review.
- `sort` accepts a whitelist per endpoint; `-` prefixes descending.
- `q` is full-text/trigram search, scoped to the endpoint's resource.
- `fields` is optional projection for heavy resources.
- `expand=team,person` inlines related resources where the alternative is a
  guaranteed N+1 on the client.

## 5. Error format

One envelope everywhere:

```json
{
  "code": "TICKET_ALREADY_USED",
  "message": "This ticket was already scanned at Gate B.",
  "details": {
    "ticket_id": "018f…",
    "scanned_at": "2026-08-13T18:42:11Z",
    "gate": "B"
  },
  "request_id": "01J9…"
}
```

| Field | Contract |
| --- | --- |
| `code` | `SCREAMING_SNAKE_CASE`, **stable**, part of the API contract, safe to branch on |
| `message` | Human-readable, localised to the request's `Accept-Language`, **never** shown as the sole explanation for a security failure |
| `details` | Structured, machine-usable, never contains internals |
| `request_id` | Correlation ID; matches logs and traces |

Validation errors add a `fields` array so forms can attach messages inline:

```json
{ "code": "VALIDATION_ERROR", "message": "…",
  "details": { "fields": [
    { "field": "kickoff_at", "code": "IN_THE_PAST", "message": "…" }]}}
```

Status codes: `400` malformed · `401` unauthenticated / step-up · `402` feature
not entitled · `403` permission denied · `404` not found *or not in scope* ·
`409` conflict (state or version) · `410` gone · `422` semantically invalid ·
`423` locked (seat held) · `429` rate limited · `500` internal.

Stack traces and database errors never reach a client. The central exception
handler maps domain exceptions to codes; anything unmapped becomes
`INTERNAL_ERROR` with a `request_id`, and the detail goes to logs and Sentry.

### Domain exception mapping

```python
class DomainError(Exception):
    code: ClassVar[str]
    status: ClassVar[int]

class TicketAlreadyUsed(DomainError):   code, status = "TICKET_ALREADY_USED", 409
class SeatUnavailable(DomainError):     code, status = "SEAT_UNAVAILABLE", 423
class PermissionDenied(DomainError):    code, status = "PERMISSION_DENIED", 403
class FeatureNotEnabled(DomainError):   code, status = "FEATURE_NOT_ENABLED", 402
class MembershipExpired(DomainError):   code, status = "MEMBERSHIP_EXPIRED", 409
class LimitExceeded(DomainError):       code, status = "LIMIT_EXCEEDED", 409
```

Every error code is registered in a single enum, exported into the OpenAPI
schema, and generated into the TypeScript client — so the frontend gets
autocomplete on error codes and a compile error when one is removed.

## 6. Idempotency

`Idempotency-Key` is **required** on `POST` to: checkout sessions, orders,
refunds, ticket issuance, membership creation, transfers, and any endpoint that
moves money or inventory. Optional elsewhere, honoured everywhere on `POST`.

Semantics: the first request with a key executes and stores its response; a
replay within 24 hours returns the stored response with
`Idempotency-Replayed: true`. A replay with a *different* body returns `409
IDEMPOTENCY_KEY_REUSED` — silently returning the first response for different
input hides client bugs.

## 7. Concurrency control

Editable resources return `ETag`. Updates send `If-Match`:

```
PATCH /players/018f…    If-Match: "7"
→ 409 { "code": "STALE_RESOURCE", "details": { "current_version": 9 } }
```

Applied where two staff members plausibly edit the same record at once: player
profiles, fixtures, ticket types and prices, content items, evaluations. Not
applied to append-only resources, where it is meaningless.

Ticket prices in particular: two ticketing managers adjusting prices during an
on-sale is a real scenario, and last-write-wins there costs money.

## 8. Rate limiting

| Scope | Limit |
| --- | --- |
| Unauthenticated, per IP | 60 req/min |
| Authenticated, per user | 600 req/min |
| Checkout / order creation | 10 req/min per user, 30 per IP |
| Login / password reset | 5 req/min per IP + per account (Keycloak brute-force detection on top) |
| Scan validation | 1 200 req/min per device — high on purpose |
| Public site API | 300 req/min per IP, plus CDN caching in front |
| Platform API | 120 req/min |

Sliding window in Redis. Responses carry `RateLimit-Limit`, `RateLimit-Remaining`
and `RateLimit-Reset`; `429` includes `Retry-After`.

Ticket on-sale is the case that breaks naive limits: 5 000 people hit checkout in
60 seconds, many behind the same corporate or mobile-carrier NAT. Per-IP limits
alone would lock out legitimate buyers, so on-sale windows use per-session limits
plus a queue mechanism rather than aggressive IP throttling.

## 9. Public API caching

`/api/v1/public/**` is designed for a CDN:

- `Cache-Control: public, max-age=60, stale-while-revalidate=300` for fixtures,
  standings, news lists
- `max-age=0, s-maxage=30` for live match data
- `ETag` on everything; conditional requests return `304`
- Cache keys include the resolved club (via `Vary` on host) and locale
- Publishing content purges the affected CDN paths via an event handler — so an
  editor pressing "publish" sees the article live in seconds, not in an hour

Nothing behind authentication is ever `public`-cacheable. This is asserted by a
test that sweeps every route and fails if an authenticated endpoint emits a
public cache header.

## 10. OpenAPI and client generation

FastAPI generates the schema; CI:

1. Exports it to `docs/api/openapi.v1.json`
2. Diffs it against the committed version
3. Fails on a **breaking** change without a version bump (removed endpoint or
   field, narrowed type, new required parameter) using an OpenAPI diff tool
4. Regenerates `packages/api-client` and fails if it is out of date

Every endpoint must declare `response_model`, `status_code`, `summary`, tags and
its error responses. Undocumented endpoints fail CI. The generated client is the
only way frontends call the API — hand-written `fetch` against our own API is
lint-blocked.

## 11. Conventions that are non-negotiable

- Timestamps are ISO 8601 UTC with `Z`. Never a local time, never an offset-naive
  string. The client formats for display.
- Money is always `{ "amount_minor": 1990, "currency": "EUR" }`. Never a float,
  never a preformatted string, never a bare number.
- Enums are `SCREAMING_SNAKE_CASE` strings, never integers.
- IDs are UUID strings.
- `null` means "no value"; a missing key in a `PATCH` means "unchanged". These
  are different and the API respects the difference.
- No endpoint accepts `tenant_id` in a body or query string.
- Booleans are named positively (`is_active`, not `is_not_disabled`).
