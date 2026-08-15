# 07 — Feature Entitlements

## 1. The rule

Business code must never ask what plan a tenant is on.

```python
# Forbidden — this is how plans leak into every module and become unchangeable
if tenant.plan == "PRO": ...

# Correct
await entitlements.require(ctx, Feature.TICKETING_SEATED)
```

A plan is a *commercial packaging* of features. It changes when sales says so.
If plan names appear in domain logic, every pricing experiment becomes an
engineering project and every enterprise exception becomes a special case in a
service.

## 2. Feature kinds

| Kind | Meaning | Example |
| --- | --- | --- |
| `BOOLEAN` | Module or capability on/off | `ticketing`, `loyalty`, `wallet_passes` |
| `LIMIT` | Hard ceiling, enforced at write time | `max_teams`, `max_staff_users`, `max_clubs` |
| `QUOTA` | Metered per period, soft-fails with warning then hard-fails | `emails_per_month`, `sms_per_month`, `storage_gb` |

Initial feature keys:

```
Modules      academy, ticketing, season_tickets, memberships, shop, fundraising,
             loyalty, sponsorship, cms, scouting, medical, analytics_advanced,
             training_advanced, resale, wallet_passes, custom_domain,
             api_access, sso_enterprise
Limits       max_clubs, max_teams, max_players, max_staff_users, max_venues,
             max_ticketed_events_per_season, max_custom_domains
Quotas       emails_per_month, sms_per_month, storage_gb, api_calls_per_day
```

## 3. Resolution

Effective entitlement = plan features, overlaid by tenant overrides:

```
plan_version → plan_feature        (the packaged baseline)
      ⊕
entitlement (source = OVERRIDE | TRIAL | PROMO, time-bounded)
      =
effective entitlement for (tenant, feature, now)
```

Overrides exist because enterprise deals always contain exceptions. An override
carries `granted_by` and `reason`, is time-bounded, and appears in the tenant's
audit log — so "why does this tenant have resale enabled?" always has an answer.

Resolved once per request, cached in Redis (`ent:v{n}:{tenant_id}`, 5 min TTL,
explicitly invalidated on subscription or override change). The cache is
populated from a single query returning the full feature map — never one query
per feature check.

```python
@dataclass(frozen=True)
class Entitlements:
    def enabled(self, f: Feature) -> bool: ...
    def limit(self, f: Feature) -> int | None: ...      # None = unlimited
    def require(self, f: Feature) -> None:              # raises FeatureNotEnabled
```

## 4. Enforcement points — all four are required

**1. Backend route guard.** Declarative, next to the permission check:

```python
ctx: Annotated[RequestContext, Requires("ticketing.event.manage",
                                        scope=Club, feature=Feature.TICKETING)]
```

**2. Backend service guard** for anything reachable outside HTTP — Celery tasks,
webhook handlers, event consumers. A disabled feature must not keep processing in
the background just because no route was involved.

**3. Limit checks at write time**, inside the service, in the same transaction as
the insert:

```python
async def create_team(self, data: TeamCreate, ctx: RequestContext) -> Team:
    await self.entitlements.check_limit(ctx, Feature.MAX_TEAMS,
                                        current=await self.repo.count_active(ctx))
    ...
```

Counting inside the transaction avoids the race where two concurrent creates both
see `n-1`. For limits where that race matters commercially, a database-level
constraint backs it up.

**4. Frontend gating.** The session bootstrap response includes the resolved
feature map; navigation, buttons and routes are hidden or shown from it.

> Frontend hiding is **presentation, not authorization**. Every gated capability
> is enforced on the server. The permission-matrix test suite asserts that each
> entitlement-gated route returns 402 when the feature is off, independent of
> what the UI does.

## 5. Behaviour when a feature is turned off

Disabling is not deleting. When `shop` is disabled mid-season:

| Aspect | Behaviour |
| --- | --- |
| Existing data | Retained, untouched |
| Admin UI | Module hidden from navigation |
| Public site | Shop routes 404; navigation entries removed |
| In-flight orders | Complete normally — a paid order is always fulfilled |
| Refunds | Always remain possible, regardless of entitlement |
| Re-enabling | Everything reappears exactly as it was |

Refunds and fulfilment of already-paid orders are *never* gated. Taking someone's
money and then blocking their refund because a subscription lapsed is not a
technical failure mode we are willing to have.

## 6. Degradation on non-payment

Tied to `tenant.status` (see [04 §5](04-multitenancy.md)):

| Tenant status | Entitlements |
| --- | --- |
| `ACTIVE` | Full |
| `PAST_DUE` | Full, with an in-app banner and email escalation |
| `SUSPENDED` | Admin read-only; public site shows maintenance; **ticket scanning still works**; refunds still work |
| `CLOSED` | Export only, for the contractual window |

## 7. Error contract

```json
{
  "code": "FEATURE_NOT_ENABLED",
  "message": "Seated ticketing is not included in your plan.",
  "details": { "feature": "ticketing_seated", "plan": "club", "upgrade_to": "pro" }
}
```

HTTP `402 Payment Required` — semantically correct, and distinct from `403`, so
the frontend can render an upgrade prompt rather than an access-denied page. For
limits: `409` with `code: LIMIT_EXCEEDED` and `details: {limit, current}`.
