# ADR-0004 — Separate `User` (authentication) from `Person` (human)

**Status:** Accepted · **Date:** 2026-08-13

## Context

The same human appears in many roles. A club's youth coach is often also a parent
of an academy player and a season-ticket holder. An academy player becomes a
first-team player, then a member. A supporter's child joins the academy.

Many people in the system have **no login at all**: a U9 player, a supporter
entered from a paper form, an emergency contact.

The naive model — one `user` table with `is_player`, `is_coach`, `is_parent`
booleans — fails immediately on both counts.

## Decision

Three separate concepts:

```
user_account   authentication identity   global, one per login    (mirrors Keycloak)
person         a human being             one per tenant
role_assignment  what they may do        scoped to tenant/club/team
```

- `person.user_id` is nullable. People exist without logins.
- One `user_account` may link to several `person` rows across tenants.
- Domain attachments (`player`, `staff_profile`, `fan_profile`,
  `guardian_relationship`) reference `person_id`, never duplicate identity fields.
- `person` is **tenant-scoped**: each tenant is an independent data controller.

## Consequences

**Good.**
- A person appears once. "Fan 360" can show that a supporter is also the parent
  of two academy players without any reconciliation logic.
- GDPR erasure has exactly one place to anonymise, and it severs the link
  everywhere at once — which is what makes
  [Q7](../architecture/open-questions.md#q7) tractable at all.
- Adding a role never touches identity storage.
- A minor without an email is a first-class citizen of the model.

**Bad.**
- Every domain query joins `person`. Mitigated by `person_role_flag`, a small
  denormalised table answering "is this person a player/staff/guardian/fan?"
  without six LEFT JOINs.
- Duplicate `person` rows will occur (staff enter a supporter who later
  self-registers). Requires a merge tool with audit — planned for Phase 2, not
  optional, because manual duplicate cleanup does not scale past a few hundred.
- A fan of two clubs in different tenants is two `person` rows, so cross-tenant
  fan analytics is impossible by design. Correct, but must be communicated —
  see [Q11](../architecture/open-questions.md#q11).

**Why not one global `person`.** Club A's edits would affect Club B's record, and
an erasure request would span two data controllers. Legally wrong, and
operationally worse.
