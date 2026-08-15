# ADR-0006 — Ticket / credential separation and offline validation

**Status:** Accepted · **Date:** 2026-08-13

## Context

A ticket is a commercial fact: someone bought the right to attend. A credential
is a technical fact: this QR code opens this turnstile. They have different
lifecycles — a ticket transferred to a friend is the same purchase but must be a
different credential, and the old one must die instantly.

Access technology will change (static QR → rotating QR → Apple/Google Wallet →
NFC) while ownership records must remain stable and auditable for years.

Stadium connectivity fails. It fails most often when 4 000 people arrive at once
and saturate the same cell tower the scanners use.

## Decision

### Separate `ticket` from `access_credential`

One ticket may have many credentials over its life; exactly one is `ACTIVE`.
Transfer, resale and wallet re-issuance revoke and supersede credentials without
touching ownership history.

### Credentials are opaque and signed

The QR carries an opaque identifier plus an Ed25519 signature over
`(credential_ref, event_id, section, gate_mask, valid_window, key_id)`.

It carries **no** personal data — no name, no email, no seat description. A
photographed ticket must reveal nothing about its holder. `key_id` allows key
rotation without invalidating issued credentials.

### Single admission is a database constraint

```sql
UNIQUE (credential_id) WHERE result = 'VALID'   -- on ticket_scan
```

A duplicate scan attempts an insert, violates the constraint, and is converted to
`ALREADY_USED` — which is itself recorded as a separate non-`VALID` row. No
application locking, correct under any concurrency, correct across replicas.

### Offline validation

Before the match, each device downloads a signed manifest for its event and
gates: credential digests, a Bloom filter for fast negative lookup, and a
revocation list. Offline, the device verifies the signature locally, checks the
manifest, decides in under 150 ms, and queues the scan. Scans flush continuously
when connectivity returns.

Manifests are **gate-partitioned**: a credential valid only at Gate B is absent
from Gate D's manifest.

## Consequences

**Good.** Wallet passes and rotating QR are additive in Phase 4 with no change to
`ticket`. Transfer and resale are credential operations. The turnstile keeps
working when the WAN does not. Ownership and access are separately auditable.

**Bad.**
- Two tables where one seems sufficient — worth explaining to every new engineer.
- Manifest distribution is real work: generation, signing, size management
  (~8 000 credentials ≈ 300 kB), pre-match download UX, and staleness handling.
- **Two fully disconnected devices cannot detect a duplicate between them.** This
  is a mathematical limit, not a gap. Gate partitioning shrinks it to near zero
  for seated tickets; GA at a shared gate remains exposed for the duration of the
  outage. Post-match reconciliation flags every duplicate with gate, device and
  operator. This must be accepted in writing by the club — see
  [Q5](../architecture/open-questions.md#q5).
- Offline mode is an explicit, audited operator action with a persistent banner,
  never a silent fallback. A steward must always know which guarantee they are
  operating under.
