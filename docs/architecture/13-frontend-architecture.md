# 13 — Frontend Architecture

## 1. Four applications, two rendering strategies

| App | Stack | Why |
| --- | --- | --- |
| `public-web` | **Next.js 15**, App Router, RSC | SEO, social sharing, Core Web Vitals, multi-domain routing, ISR for news and fixtures |
| `admin-web` | **React 19 + Vite + TanStack Router** | Authenticated, indexed by nobody. SSR would add cost with no benefit |
| `super-admin` | Same as admin-web | Same reasoning, separate deployable for blast-radius isolation |
| `scanner` | React + Vite + Workbox PWA | Must run offline. SSR is actively wrong here |

**Why not Next.js everywhere.** SSR earns its complexity when first-paint on an
uncached, unauthenticated page matters. For an admin tool behind a login, it buys
nothing and costs a server runtime, a hydration model, and a data-fetching split
between server and client that every engineer must hold in their head. Vite SPAs
build to static assets served from a CDN with no runtime at all.

**Why super-admin is a separate app rather than a route in admin-web.** A routing
or permission bug in a shared bundle could expose platform tooling to a club
administrator. Separate deployable, separate OIDC client, separate hostname,
mandatory MFA. The isolation is worth the small duplication.

## 2. Shared packages

```
packages/
├── ui/           design system — tokens, primitives, patterns, icons
├── api-client/   generated from OpenAPI + typed fetch wrapper + TanStack Query hooks
├── auth/         OIDC client, session context, <Can> guard, useEntitlement
├── i18n/         ICU message catalogues, locale/date/number/currency helpers
├── types/        cross-app types not derived from the API
├── validation/   Zod schemas mirroring API contracts
└── config/       eslint, tsconfig, tailwind preset, prettier, vitest base
```

`api-client` is generated in CI and committed, so a stale client is a visible
diff rather than a runtime surprise. It exports typed query/mutation hooks:

```ts
const { data, isLoading } = usePlayersList({ team_id, status: "REGISTERED" })
const { mutate } = useCreatePlayer()   // Idempotency-Key attached automatically
```

## 3. Data layer

**TanStack Query** for all server state. Rules:

- Server state is never copied into `useState` or a global store. The cache *is*
  the state.
- Query keys are structured and generated: `["players", "list", filters]`.
- Mutations invalidate precisely; blanket `invalidateQueries()` is lint-blocked.
- Optimistic updates only where rollback is genuinely safe. Never for money,
  inventory or scanning.
- Errors surface as typed `ApiError` with the `code` from
  [12 §5](12-api-conventions.md), so components branch on codes, not strings.

Client state (sidebar state, table density, filter drafts) uses Zustand or plain
context. There is no Redux and no global store of domain data.

**Forms**: React Hook Form + Zod resolver, with schemas from
`packages/validation` mirroring the API contract. Client validation is UX;
the server validates independently and is authoritative. Server field errors map
back onto form fields via the `details.fields` array.

## 4. `public-web` — multi-tenant, multi-domain

Tenant resolution happens in middleware from the `Host` header:

```ts
// middleware.ts
const club = await resolveClubByHost(request.headers.get("host"))
if (!club) return notFound()
requestHeaders.set("x-club-id", club.id)
```

Resolution is cached (Redis, 5 min) because it runs on every request. An unknown
host 404s — it never falls back to a default club, which would serve one club's
content on another's domain.

Rendering strategy per route:

| Route | Strategy | Revalidation |
| --- | --- | --- |
| Home, fixtures, results, team | ISR | 60 s + on-demand via `ContentPublished` |
| News list / article | ISR | 300 s + on-demand |
| Player / staff profile | ISR | 3600 s + on-demand |
| Shop catalogue | ISR | 300 s |
| Ticket availability | Dynamic | never cached |
| Checkout, account, cart | Dynamic, no cache | — |

**ISR in containers requires a shared cache handler.** With multiple replicas,
Next's default filesystem cache means each replica has its own copy and
on-demand revalidation only reaches one of them — so an editor publishes an
article and it appears on refresh, then disappears, then reappears. We configure
a Redis-backed `cacheHandler` from the start. This is a well-known trap that is
painful to retrofit and invisible on a single-replica staging environment.

Branding is applied by injecting the club's tokens as CSS custom properties in
the root layout — no per-tenant builds, no runtime theme switching flash.

## 5. `scanner` — offline-first PWA

The most constrained app in the system. Design constraints:

- One-handed operation, gloves, cold, dark, rain, 90 seconds of queue behind
  every person.
- Camera-based QR scanning at 30 fps via `BarcodeDetector` where available, with
  `zxing-wasm` as fallback.
- **Decision must render in under 150 ms**, offline or online.

Architecture:

```
Pre-match:  download signed credential manifest for the event  →  IndexedDB
            (bloom filter + signed credential digests + revocation list)
Scan:       decode QR → verify signature locally → check local status
            → render decision immediately
            → enqueue scan record
Online:     flush queue continuously; server returns authoritative corrections
Offline:    queue persists; banner shows "OFFLINE — N scans pending"
Post-match: forced sync before the session can be closed
```

Service worker (Workbox) precaches the shell; the manifest is in IndexedDB, not
the SW cache, because it is data, not assets.

**Status display** — deliberately not colour-dependent (rain, glare, colour-blind
operators, cheap screens):

| Result | Presentation |
| --- | --- |
| `VALID` | Full-screen green, large ✓, single ascending beep, short haptic |
| `ALREADY_USED` | Full-screen amber, ⟳ icon, **shows previous scan time and gate**, double beep, long haptic |
| `WRONG_GATE` | Amber, → arrow icon, names the correct gate |
| `WRONG_EVENT` / `OUTSIDE_WINDOW` | Amber, calendar icon, names the event and window |
| `REVOKED` / `INVALID` | Full-screen red, ✕, triple beep, long double haptic |
| `OFFLINE_VALID` | Green with a persistent offline badge — honest about the weaker guarantee |

Icon + text + sound + haptics, always. Colour is reinforcement, never the signal.

The steward never sees a spinner. If the network is slow, the local decision has
already rendered and the server reconciles afterwards.

## 6. `admin-web` — operational shell

```
┌─────────────────────────────────────────────────────────┐
│ Club switcher ▾    ⌘K search            Season ▾   ○ me │
├──────────┬──────────────────────────────────────────────┤
│ Overview │  Page title              [Primary action]    │
│ Academy  │  ─────────────────────────────────────────── │
│ Teams    │  Filters · saved views                       │
│ Players  │  ┌────────────────────────────────────────┐  │
│ Training │  │ dense, sortable, selectable table      │  │
│ Matches  │  │ bulk actions appear on selection       │  │
│ Ticketing│  └────────────────────────────────────────┘  │
│ Shop     │  cursor pagination · 25 / 50 / 100           │
│ Members  │                                              │
│ Content  │                                              │
│ Finance  │                                              │
│ Settings │                                              │
└──────────┴──────────────────────────────────────────────┘
```

- Navigation is generated from resolved permissions + entitlements. A section the
  user cannot use does not render (and its route also 403s server-side).
- `⌘K` command palette navigates and executes actions — the primary interface for
  daily users, who will never use the sidebar after week two.
- Tables use TanStack Table with server-side sorting, filtering and pagination.
  Client-side table state on a 12 000-row supporter list is not viable, so it is
  never built that way even for small lists.
- URL is the source of truth for filters, sort, page and selected view — so a
  filtered list is shareable and survives a refresh.
- Every list has saved views; every list has a CSV/XLSX export that runs as a
  background job with a download notification, not a blocking request.

## 7. Internationalisation

Shared catalogues in **ICU MessageFormat** under `packages/i18n`, consumed by
`next-intl` in `public-web` and `react-intl` in the SPAs. Both consume ICU, so
the catalogues are the portable artefact and only the runtime binding differs —
this avoids either a lowest-common-denominator library or two incompatible
message formats.

Rules:

- No hardcoded user-facing strings. ESLint `no-literal-string` on JSX text.
- Dates, numbers and currency via `Intl`, with the tenant's timezone and the
  user's locale. Never manual formatting, never assumed `dd/mm/yyyy`.
- Pluralisation and gender through ICU, never string concatenation.
- Locale is chosen: user preference → tenant default → `Accept-Language` →
  platform default (`en`).
- Layout is tested at +40 % string length (German compounds break narrow buttons
  and table headers, reliably).
- Content translations (CMS) are separate from UI translations — different
  lifecycle, different authors, different storage.

Launch locales: `en`, `ro`, `de`. Nothing in the code knows those three exist.

## 8. Performance budgets

| App | Budget |
| --- | --- |
| `public-web` | LCP < 2.0 s on 4G mid-tier Android; JS < 120 kB gzipped initial |
| `admin-web` | Interactive < 2.5 s cold, < 500 ms route change; route-level code splitting |
| `scanner` | Shell < 60 kB; scan decision < 150 ms; fully functional offline |

Enforced in CI with Lighthouse CI on `public-web` and bundle-size checks on all
four. A budget without a gate is a wish.

## 9. Accessibility

Target **WCAG 2.2 AA** on: fan registration, ticket purchase, membership
purchase, academy registration, the parent portal, and all public content pages.

- Radix primitives give correct focus management, roles and keyboard behaviour.
- Every interactive element is keyboard reachable with a visible focus ring.
- Contrast is validated — including club brand colours, which are contrast-checked
  at upload time and automatically substituted with an accessible variant for
  text use if they fail. A club's brand colour is not allowed to make its own
  ticket checkout unusable.
- `axe-core` runs in component tests and in Playwright E2E; violations fail CI.
- Forms use real labels, `aria-describedby` error association, and never rely on
  placeholder text as a label.
