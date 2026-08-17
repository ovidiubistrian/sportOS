"""Minting, signing and revoking the QR a supporter shows at the turnstile.

Implements ADR-0006. Two properties matter more than anything else here.

**The code is opaque.** It carries a random reference and a signature, and
nothing else — no name, no email, no order number, no seat description. A
ticket photographed and posted to social media, which happens constantly, must
reveal nothing about the person holding it. The seat is printed *beside* the
barcode, never inside it.

**The code is signed, so a scanner can reject a forgery with no network.** The
signature covers `(reference, event, section, gates, validity window, key id)`
with Ed25519. A device holding only the public key can verify locally in under
a millisecond, which is what makes offline validation possible at all. `key_id`
travels with the credential so keys can be rotated without invalidating
everything already issued.

Note what signature verification does *not* prove: that the ticket has not
already been used. A forged code fails the signature; a genuine code scanned
twice passes it. Single admission is a database constraint — see
`access_models.ScanLog` — and no amount of cryptography substitutes for it.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFound
from app.ticketing.ticket_models import AccessCredential, Ticket

# 20 random bytes — 160 bits — url-safe encoded. Long enough that guessing is
# hopeless, short enough to fit a QR at a size a phone screen renders legibly.
_REFERENCE_BYTES = 20

# The separator inside the scanned payload. A dot rather than a colon or slash
# so the whole string survives being put in a URL or read down a phone line.
_SEPARATOR = "."


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _private_key() -> Ed25519PrivateKey:
    """Derive the signing key from the configured seed.

    Hashed to 32 bytes rather than requiring the operator to supply exactly 32,
    so a deployment cannot half-work with a seed of the wrong length.
    """
    seed = settings.ticket_signing_key.get_secret_value().encode()
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed).digest())


def public_key_base64() -> str:
    """What a scanner needs to verify offline. Safe to hand out."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return _b64(_private_key().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def key_id() -> str:
    """A short fingerprint of the signing key, carried on every credential.

    Reading `dev` in production is the signal that the real key was never
    configured — which is exactly the kind of thing that otherwise ships
    unnoticed and works fine until somebody forges a ticket.
    """
    seed = settings.ticket_signing_key.get_secret_value()
    if seed.startswith("ZGV2LW9ubHkt"):  # the published dev default
        return "dev"
    return hashlib.sha256(public_key_base64().encode()).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class CredentialClaims:
    """Exactly what the signature covers. Nothing personal appears here."""

    reference: str
    event_id: UUID
    section_code: str
    gate_codes: str
    valid_from: datetime | None
    valid_until: datetime | None
    key_id: str

    def canonical(self) -> bytes:
        """The signed byte string.

        Field order is fixed and every field is present even when empty. A
        canonical form that varies by which fields happen to be set is one
        where two different claim sets can produce the same bytes.
        """
        parts = [
            self.reference,
            str(self.event_id),
            self.section_code or "",
            self.gate_codes or "",
            self.valid_from.isoformat() if self.valid_from else "",
            self.valid_until.isoformat() if self.valid_until else "",
            self.key_id,
        ]
        return "|".join(parts).encode()


def sign(claims: CredentialClaims) -> str:
    return _b64(_private_key().sign(claims.canonical()))


def verify(claims: CredentialClaims, signature: str) -> bool:
    """Whether this signature was made by us over these exact claims."""
    try:
        _private_key().public_key().verify(_unb64(signature), claims.canonical())
    except (InvalidSignature, ValueError):
        return False
    return True


def verify_with_key(claims: CredentialClaims, signature: str, public_key_b64: str) -> bool:
    """Offline verification path — what the Android client will run.

    Present here so the server and the future device provably share one
    implementation, and so the browser scanner can exercise it.
    """
    try:
        Ed25519PublicKey.from_public_bytes(_unb64(public_key_b64)).verify(
            _unb64(signature), claims.canonical()
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def qr_payload(credential: AccessCredential) -> str:
    """The string encoded into the QR image: `reference.signature`.

    Deliberately not JSON and not a URL. Shorter payloads make denser codes,
    which scan faster in bad light at a turnstile — and a code that scans on
    the first try is the difference between a queue that moves and one that
    does not.
    """
    return f"{credential.reference}{_SEPARATOR}{credential.signature}"


def split_payload(scanned: str) -> tuple[str, str | None]:
    """Pull a reference out of whatever the scanner actually read.

    Accepts a bare reference too, because the box office types those by hand
    off a printed ticket when a phone screen is too cracked to scan.
    """
    value = (scanned or "").strip()
    if _SEPARATOR in value:
        reference, _, signature = value.partition(_SEPARATOR)
        return reference.strip(), signature.strip()
    return value, None


async def mint(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    ticket: Ticket,
    event_id: UUID,
    section_code: str,
    gate_codes: str = "",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    supersedes: AccessCredential | None = None,
) -> AccessCredential:
    """Issue the one live credential for a ticket.

    Any existing active credential is revoked first, in the same transaction.
    That is what makes a transfer safe: the old QR stops working the instant
    the new one exists, with no window in which both are valid.
    """
    await revoke_active(session, tenant_id, ticket_id=ticket.id)

    reference = secrets.token_urlsafe(_REFERENCE_BYTES)
    claims = CredentialClaims(
        reference=reference,
        event_id=event_id,
        section_code=section_code,
        gate_codes=gate_codes,
        valid_from=valid_from,
        valid_until=valid_until,
        key_id=key_id(),
    )

    credential = AccessCredential(
        tenant_id=tenant_id,
        ticket_id=ticket.id,
        event_id=event_id,
        reference=reference,
        signature=sign(claims),
        key_id=claims.key_id,
        status="ACTIVE",
        section_code=section_code,
        gate_codes=gate_codes or None,
        valid_from=valid_from,
        valid_until=valid_until,
        issued_at=datetime.now(UTC),
        supersedes_id=supersedes.id if supersedes else None,
        version=(supersedes.version + 1) if supersedes else 1,
    )
    session.add(credential)
    await session.flush()
    return credential


async def revoke_active(
    session: AsyncSession, tenant_id: UUID, *, ticket_id: UUID
) -> AccessCredential | None:
    """Kill the live credential for a ticket, if there is one."""
    current = await session.scalar(
        select(AccessCredential).where(
            AccessCredential.tenant_id == tenant_id,
            AccessCredential.ticket_id == ticket_id,
            AccessCredential.status == "ACTIVE",
        )
    )
    if current is None:
        return None
    current.status = "SUPERSEDED"
    current.revoked_at = datetime.now(UTC)
    await session.flush()
    return current


async def reissue(
    session: AsyncSession, tenant_id: UUID, *, ticket_id: UUID
) -> AccessCredential:
    """Replace a ticket's QR — a transfer, a lost phone, a wallet re-add."""
    ticket = await session.scalar(
        select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.id == ticket_id)
    )
    if ticket is None:
        raise NotFound("That ticket does not exist.")

    previous = await session.scalar(
        select(AccessCredential)
        .where(
            AccessCredential.tenant_id == tenant_id,
            AccessCredential.ticket_id == ticket_id,
        )
        .order_by(AccessCredential.version.desc())
    )
    return await mint(
        session,
        tenant_id,
        ticket=ticket,
        event_id=ticket.event_id,
        section_code=previous.section_code if previous else "",
        gate_codes=(previous.gate_codes or "") if previous else "",
        valid_from=previous.valid_from if previous else None,
        valid_until=previous.valid_until if previous else None,
        supersedes=previous,
    )
