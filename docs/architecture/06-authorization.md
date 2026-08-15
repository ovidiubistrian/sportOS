# 06 — Authorization: Scoped RBAC

## 1. The decision rule

Every authorization decision answers one question:

> Does this **user** hold a **permission** at a **scope** that contains this
> **object**, for a tenant whose plan **entitles** the feature?

Four inputs, evaluated in a fixed order. Failing early is cheaper and produces
better errors:

```
1. Authenticated?          → 401 UNAUTHENTICATED
2. Tenant context valid?   → 404 (never reveal existence)
3. Feature entitled?       → 402 FEATURE_NOT_ENABLED
4. Permission at scope?    → 403 PERMISSION_DENIED
5. Object inside scope?    → 404 (never reveal existence)
6. Sensitive → step-up?    → 401 STEP_UP_REQUIRED
```

Steps 2 and 5 return **404, not 403**. A 403 on an object from another tenant
confirms that the object exists, which is itself a leak.

## 2. Permissions

Permissions are `module.object.action` strings, defined in code, seeded to the
database:

```
clubs.club.read           clubs.club.update
players.player.read       players.player.create      players.player.delete
players.document.read     players.document.upload
training.session.read     training.session.manage    training.attendance.record
development.evaluation.read_own_team
development.evaluation.read_any
medical.record.read       medical.record.write       medical.availability.set
ticketing.event.manage    ticketing.price.update     ticketing.order.refund
access.scan               access.device.manage
commerce.order.read       commerce.order.fulfil
finance.report.read       finance.payout.configure
billing.subscription.read
cms.content.publish
people.person.export      privacy.request.handle
platform.tenant.manage    platform.impersonate
```

Roughly 120 permissions at full scope. Business logic **never** checks a role
name — only permission keys. This is what makes tenant-defined custom roles
possible without touching code.

Permissions carry metadata:

```python
Permission(
    key="ticketing.order.refund",
    module="ticketing",
    scope_levels=[TENANT, CLUB],      # cannot be granted at team level
    is_sensitive=True,                # forces audit + step-up
)
```

## 3. Scopes

A scope is a triple, from broadest to narrowest:

```
PLATFORM                        (tenant_id NULL)
TENANT   → tenant_id
CLUB     → tenant_id, club_id
TEAM     → tenant_id, club_id, team_id
```

A `role_assignment` grants a role at a scope. Containment is strict: a permission
held at `CLUB` covers all teams in that club; a permission held at `TEAM` covers
only that team.

Worked example — the requirement in the brief:

```
Person: Ana Popescu
  role_assignment: role=COACH, tenant=fc-example, club=fc-example, team=U15
```

`COACH` grants `players.player.read`, `training.session.manage`,
`training.attendance.record`, `development.evaluation.read_own_team`,
`matches.squad.manage`. Therefore Ana can:

- read and manage U15 players, sessions, attendance, squads ✓
- read U17 players ✗ — permission held only at TEAM scope, U17 not in scope → 404
- read `finance.report.read` ✗ — `COACH` does not grant it → 403
- read a diagnosis ✗ — see §5

## 4. Resolution and caching

```python
@dataclass(frozen=True)
class EffectivePermissions:
    tenant_id: UUID
    # permission key → the scopes at which it is held
    grants: Mapping[str, frozenset[Scope]]

    def allows(self, permission: str, scope: Scope) -> bool:
        return any(held.contains(scope) for held in self.grants.get(permission, ()))
```

Resolved once per request from `role_assignment ⋈ role_permission`, cached in
Redis under `perm:v{n}:{user_id}:{tenant_id}` with a 60 s TTL.

Invalidation is explicit: any write to `role_assignment`, `role_permission` or
`role` bumps a per-user version key, so changes take effect on the next request,
not after a minute. The TTL is a safety net, not the mechanism.

FastAPI usage stays declarative:

```python
@router.post("/events/{event_id}/prices")
async def update_prices(
    event_id: UUID,
    payload: PriceUpdate,
    ctx: Annotated[RequestContext, Requires("ticketing.price.update", scope=Club)],
    service: Annotated[TicketPricingService, Depends()],
) -> PriceResponse:
    return await service.update_prices(event_id, payload, ctx)
```

`Requires` resolves entitlement + permission + scope, and records an audit entry
when the permission is `is_sensitive`. The router does nothing else.

**Object-level check.** Permission at a scope is not sufficient — the object must
be inside the scope. Repositories already filter by tenant; scope narrowing
(club/team) is applied by the service through a `ScopeFilter` derived from the
request context, so a coach's "list players" query returns only their teams
rather than returning everything and filtering in Python.

## 5. Medical data — structural, not just RBAC

Permission checks alone are one bug away from exposing a child's medical
diagnosis. Three independent barriers:

1. **Separate schema.** `medical.*` (see [03 §7](03-data-model.md)).
2. **Separate database role and connection pool.** The default runtime role has
   **no privileges at all** on the `medical` schema. A request only obtains a
   `medical`-capable connection through
   `async with medical_scope(ctx)`, which asserts the medical permission and
   writes an audit record. A SQL injection or ORM mistake in `ticketing` cannot
   read a diagnosis because its connection lacks the grant.
3. **Coach-facing projection.** Coaches read `player_availability`
   (`AVAILABLE` / `LIMITED` / `UNAVAILABLE` + a non-clinical note). There is no
   join path from a coach's session to clinical detail.

Every read of `medical.*` writes an `audit_log` row including the specific record
accessed. Medical staff are told this at login. Step-up authentication applies.

## 6. Portal roles

Portal users (player, guardian, member, supporter) are **not** modelled as staff
roles with narrow permissions. They use a distinct authorization path:

```
Guardian → guardian_relationship → minor_person_id → player
```

A guardian's access is derived from the *relationship*, with per-relationship
flags (`may_view_development`, `may_receive_communications`, `may_collect`) — not
from a role grant. This matters because a parent's access must automatically end
when the relationship ends, and must be independently controllable per child.

Portal endpoints live under `/api/v1/portal/**` with their own dependency
(`RequiresPortalAccess`) that resolves the subject relationship. They never share
a router with staff endpoints — that separation is what stops a permission
mistake from turning a parent into a club administrator.

## 7. Role templates shipped

Seeded as `is_system` roles, cloneable and editable per tenant:

**Platform**: Super Admin, Platform Support, Platform Finance
**Tenant/Club**: Tenant Owner, Club President, Club Admin, General Manager,
Sporting Director, Finance Manager, Academy Director, Head Coach, Coach,
Assistant Coach, Scout, Team Manager, Physio/Medical, Ticketing Manager,
Matchday Manager, Steward, Shop Manager, Content Manager, Marketing Manager

Two constraints on the templates:

- **Tenant Owner is the only role that can grant Tenant Owner**, and a tenant
  must always retain at least one — enforced in the service, tested.
- No tenant role can grant a platform permission. `role.scope_level` and
  `permission.scope_levels` make that unrepresentable rather than merely
  forbidden.

## 8. Platform access and impersonation

Platform staff hold platform permissions and, by default, see only tenant
*metadata*: subscription status, usage counts, health, error rates, payment
state. They cannot read tenant business data.

To go further, they open an **impersonation session**:

- requires a written reason and (for tenants on an enterprise contract) an
  approval by a second platform user;
- is time-limited (default 60 minutes, hard maximum 4 hours);
- issues a token carrying `impersonated_by`, which is written into every
  `audit_log` row produced during the session;
- is **read-only by default**; write access is a separate, separately-audited
  elevation;
- renders a persistent, non-dismissible banner in `admin-web`;
- **notifies the tenant owner by email when it starts** — not just afterwards in
  a log they will never read;
- never exposes credentials, and never grants medical-schema access. Medical data
  is out of reach for platform staff entirely, with no override. A support case
  needing it is handled by the tenant, not by us.

Every impersonation session is listed in the tenant's own security settings page.
Transparency to the customer is the control that actually works.

## 9. Testing

- **Permission matrix test**: for every route × every seeded role template,
  assert allow/deny against an expected matrix checked into the repo. A new route
  with no matrix entry fails CI — so permissions cannot be forgotten.
- **Scope narrowing test**: a team-scoped coach cannot reach sibling teams, via
  every route that accepts a team-scoped object.
- **Privilege escalation test**: no role can grant itself or a broader role;
  no tenant role reaches platform endpoints.
- **Medical isolation test**: with a non-medical connection, every `medical.*`
  table raises insufficient privilege at the database level.
- **Portal test**: a guardian reaches exactly their own children's data, and
  loses access the moment the relationship ends.
