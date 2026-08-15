# 05 — Identity & Authentication

## 1. The three-concept split

| Concept | Owned by | Scope | Meaning |
| --- | --- | --- | --- |
| `User` (`user_account`) | Keycloak + our mirror table | Global | An authentication identity — something that can log in |
| `Person` | Us | Per tenant | A human being known to a club |
| `Role assignment` | Us | Per tenant/club/team | What that human may do |

One user may map to several persons (a supporter of two clubs held by different
tenants). One person may exist without a user (a U9 player who has no login, a
supporter entered by staff from a paper form). One person may hold many roles
(coach + parent + season-ticket holder) and appears exactly once.

This is the single most important structural decision in the identity area: it is
what prevents the same human existing five times across five modules, and what
makes "Fan 360" and GDPR erasure tractable.

## 2. Keycloak topology

**One realm — `football-os` — for all tenants and all populations.**

Alternatives considered:

| Option | Verdict |
| --- | --- |
| Realm per tenant | Rejected. 300 realms is 300 sets of clients, mappers, identity providers and upgrade surfaces. Keycloak's admin API becomes the bottleneck, realm caching costs memory linearly, and cross-tenant fan identity becomes impossible. |
| Realm per population (staff / fan) | Rejected. Duplicate identity for the coach who is also a season-ticket holder; two token issuers in every frontend. |
| **Single realm, tenant as attribute + group** | **Chosen.** |

Realm layout:

```
realm: football-os
├── clients
│   ├── admin-web         public, PKCE, standard flow
│   ├── super-admin       public, PKCE, MFA required by flow binding
│   ├── public-web        public, PKCE (fan login)
│   ├── scanner           public, PKCE, short access-token lifetime
│   └── backend-api       bearer-only / confidential (service account for admin API)
├── groups
│   └── /tenants/{tenant_slug}          membership → tenant claim
│   └── /platform/{support|finance|admin}
├── identity providers
│   ├── google
│   └── apple
└── authentication flows
    ├── browser-standard          (fans)
    ├── browser-staff-mfa         (staff — MFA required)
    └── browser-platform-mfa      (platform — MFA mandatory, no skip)
```

### What Keycloak owns

Credentials, password policy, MFA (TOTP + WebAuthn), social login, brute-force
detection, session lifetime, token issuance, account recovery.

### What Keycloak does **not** own

The business permission model. Tokens carry:

```json
{
  "sub": "…", "email": "…", "email_verified": true,
  "tenants": ["fc-example"],          // membership only
  "platform_roles": ["support"],      // platform staff only
  "amr": ["pwd", "otp"], "acr": "…"   // for step-up decisions
}
```

They do **not** carry club/team scopes or permission keys. Reasons:

- A head coach of three teams with a scout role at another club produces a token
  that would exceed practical header size.
- Permission changes must take effect immediately, not at next token refresh.
- Keycloak's admin API would become a hot write path on every role change.

Permissions are resolved server-side per request from our own tables and cached
in Redis for 60 s with explicit invalidation on assignment change. See
[06](06-authorization.md).

## 3. Token and session handling

| App | Flow | Token storage |
| --- | --- | --- |
| `admin-web`, `super-admin` | Authorization Code + PKCE | Access token in memory only; refresh via a `__Host-`-prefixed, `HttpOnly`, `SameSite=Lax`, `Secure` cookie |
| `public-web` (Next.js) | Authorization Code + PKCE, handled in route handlers | Encrypted session cookie server-side; browser never sees a token |
| `scanner` | Authorization Code + PKCE, then a **device-bound long-lived session** | See §5 |

No tokens in `localStorage`. Access-token lifetime 5 minutes (staff), 15 minutes
(fans), 60 minutes (scanner during an event window). Refresh tokens rotate; reuse
detection revokes the family.

Back-channel logout is enabled so that disabling an account in Keycloak
terminates active sessions rather than waiting for token expiry.

## 4. MFA policy

| Population | Requirement |
| --- | --- |
| Platform super admin | **Mandatory**, WebAuthn preferred, no bypass, enforced at the flow level |
| Platform support/finance | Mandatory |
| Tenant owner, club admin, finance manager | Mandatory (tenant may not disable) |
| Other staff | Enabled by default; tenant may relax, decision is audited |
| Medical staff | Mandatory + step-up (see below) |
| Fans | Optional, offered |

**Step-up authentication.** Permissions flagged `is_sensitive` (medical record
access, refunds above a threshold, permission changes, impersonation, payout
configuration) require a recent strong authentication: the token's `auth_time`
must be within 15 minutes and `amr` must include a second factor. Otherwise the
API returns `401` with `code: STEP_UP_REQUIRED`, and the frontend triggers a
re-authentication with `prompt=login&acr_values=…`.

## 5. Scanner authentication

Stewards are not trusted devices and stadium staff change every match. The
scanner uses a two-stage model:

1. **Device registration** (once, by a matchday manager): the device is enrolled,
   receives a `scanner_device` record and a device credential stored in
   IndexedDB. Registration is auditable and revocable from the admin UI.
2. **Operator session** (per shift): a steward signs in with a short PIN or a
   QR handed out by the matchday manager, bound to the registered device. This
   creates a session limited to one `ticketed_event` and one or more gates.

A lost phone is a revocation of one `scanner_device`, not a password reset for
twenty people. Every scan carries both `device_id` and `operator_user_id`.

## 6. Provisioning and the mirror table

`user_account` mirrors Keycloak. Kept in sync by:

- **Just-in-time on first token**: an unknown `sub` creates the row.
- **Admin-initiated invite**: our API creates the Keycloak user via the admin
  API (service account, narrowly scoped), sends our own branded invitation email,
  and creates `user_account` + `person` + `role_assignment` in one transaction.
- **Webhook/event reconciliation**: a nightly job reconciles disabled/deleted
  accounts.

We never store passwords, and the mirror is never authoritative for
authentication state — only for joins and referential integrity.

## 7. The white-label problem (flagged)

A fan on `fcexample.com` clicking "Sign in" is redirected to Keycloak. Out of the
box that means `auth.footbola.io` in the address bar — visible third-party
branding in the middle of a club's checkout, on a product sold as white-label.
This is a genuine conflict between two of the stated requirements.

Mitigations, in increasing order of cost:

1. **Custom Keycloak theme resolved per client/host**, rendering the club's logo
   and colours. The domain still shows `auth.footbola.io`. Cheap; covers ~80 % of
   the perception problem. *Phase 1.*
2. **CNAME per tenant** (`auth.fcexample.com` → our Keycloak) with automated
   certificate issuance. Removes the visible third-party domain entirely. Costs
   per-tenant DNS onboarding and certificate automation. *Phase 2 for clubs that
   ask.*
3. Embedding login in our own UI via the Direct Grant flow. **Rejected** — it
   means handling passwords ourselves, breaks social login and MFA flows, and
   discards the main reason for using an IdP.

Recommendation: ship (1) in Phase 1, build (2) behind an entitlement.
See [open questions](open-questions.md#q2).

## 8. Fan volume in Keycloak (flagged)

At the year-3 target this realm holds ~2.5 M users. Keycloak handles that with a
properly sized database and the user cache tuned, but two operational facts must
be planned for rather than discovered:

- User search in the admin console degrades badly at that volume — so **our**
  admin UI must never proxy Keycloak user search. It searches `person`, which is
  ours and properly indexed.
- Realm export/import is no longer a viable backup or migration mechanism at that
  size; backups are database-level.

If fan volume becomes a real operational problem, the exit is to move *fan*
authentication to a dedicated realm or a separate Keycloak cluster while staff
stay put — possible because our `user_account` table is the join key, not the
Keycloak realm. This is recorded as an escape hatch, not a plan.
