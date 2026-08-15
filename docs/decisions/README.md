# Architecture Decision Records

One record per consequential, hard-to-reverse decision. Format: Context →
Options → Decision → Consequences. Short by design; the detail lives in
`docs/architecture/`.

An ADR is never edited after acceptance except to change its status. A reversal
is a new ADR that supersedes it.

| ID | Title | Status |
| --- | --- | --- |
| [0001](ADR-0001-modular-monolith.md) | Modular monolith over microservices | Accepted |
| [0002](ADR-0002-shared-schema-multitenancy.md) | Shared database, shared schema, with RLS | Accepted |
| [0003](ADR-0003-keycloak-authentication.md) | Keycloak for authentication, application-owned authorization | Accepted |
| [0004](ADR-0004-user-person-separation.md) | Separate `User` (auth) from `Person` (human) | Accepted |
| [0005](ADR-0005-ordering-kernel.md) | One ordering kernel with per-domain line handlers | Accepted |
| [0006](ADR-0006-ticket-credentials.md) | Ticket / credential separation and offline validation | Accepted |
| [0007](ADR-0007-stripe-connect-charge-model.md) | Stripe Connect direct charges | **Proposed** — needs sign-off |
| [0008](ADR-0008-transactional-outbox.md) | Transactional outbox over a message broker | Accepted |
| [0009](ADR-0009-frontend-split.md) | Next.js for public, Vite SPAs for authenticated apps | Accepted |
| [0010](ADR-0010-deployment-topology.md) | Containers on managed infrastructure, no Kubernetes | Accepted |
| [0011](ADR-0011-ai-writing-assistant.md) | One platform-held AI key, per-tenant entitlement and quota | Accepted |

**Status meanings.** *Proposed* — decided technically, awaiting a named owner's
sign-off before implementation. *Accepted* — in force. *Superseded* — replaced,
with a link forward.
