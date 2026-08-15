# ADR-0009 — Next.js for public web, Vite SPAs for authenticated apps

**Status:** Accepted · **Date:** 2026-08-13

## Context

Four frontends with genuinely different requirements:

- **Public club websites** — SEO, social sharing cards, Core Web Vitals, custom
  domains per club, content that changes when an editor publishes.
- **Admin back office** — behind a login, indexed by nobody, dense data tables.
- **Super admin** — same, but must be isolated from tenant tooling.
- **Scanner** — must work with no network at all.

## Decision

| App | Stack |
| --- | --- |
| `public-web` | Next.js 15, App Router, RSC, ISR |
| `admin-web` | React 19 + Vite + TanStack Router |
| `super-admin` | React 19 + Vite + TanStack Router (separate deployable) |
| `scanner` | React + Vite + Workbox PWA |

All four share `packages/ui`, `api-client`, `auth`, `i18n`, `validation`.

## Rationale

**Why Next.js for public.** SEO and social previews require server-rendered HTML.
News, fixtures and player pages are read-heavy and cacheable — ISR serves them
statically and revalidates on publish. Multi-domain routing in middleware maps
`Host` → club cleanly.

**Why not Next.js everywhere.** SSR earns its complexity when first paint on an
uncached, unauthenticated page matters. Behind a login it buys nothing and costs
a server runtime to operate, a hydration model to debug, and a server/client
data-fetching split every engineer must hold in their head. Vite builds to static
assets served from a CDN with no runtime at all.

**Why super-admin is separate.** A routing or permission bug in a shared bundle
could expose platform tooling to a club administrator. Separate deployable,
separate OIDC client, separate hostname, mandatory MFA. Worth the small
duplication.

**Why the scanner is a PWA, not native.** Same React skills, same design system,
same API client, instant deployment without app-store review — which matters when
a bug is found at 14:00 for a 15:00 kick-off.

## Consequences

**Good.** Each app pays only for the complexity it needs. Static SPAs are trivial
to deploy and cache. The public site gets proper SSR/ISR. Shared packages keep
them consistent.

**Bad.**
- Two routing models and two i18n runtimes. Mitigated by keeping catalogues in
  ICU MessageFormat, which both `next-intl` and `react-intl` consume — the
  catalogues are portable, only the binding differs.
- Four build pipelines. Handled by Turborepo.
- **ISR with multiple replicas requires a shared cache handler.** Next's default
  filesystem cache means on-demand revalidation reaches one replica, so a
  published article appears, disappears and reappears depending on which replica
  serves the request. A Redis `cacheHandler` is configured from day one; this is
  invisible on single-replica staging and painful to retrofit.

**Risk.** iOS PWA camera reliability for the scanner — see
[Q6](../architecture/open-questions.md#q6). Fallbacks: Safari tab mode, external
HID barcode scanners, and a Capacitor wrapper around the same code as the last
resort.
