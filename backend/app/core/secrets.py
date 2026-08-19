"""Encrypting the credentials a club pastes in.

Every secret this platform holds on somebody else's behalf goes through here.
Not the platform's own keys — those are environment variables and stay that
way — but the ones a club types into a form: a bank's gateway password today,
an invoicing provider's tomorrow.

**Why encrypt at all, when the database is already the trust boundary.** It
buys one thing and it is worth having: a backup that leaves the building is no
longer a list of working credentials for other people's bank accounts. Dumps
get copied to laptops, sent to support, and restored into staging far more
often than a production database is breached. The key lives in the environment
and never in a dump, so the two have to be stolen separately.

It buys nothing against an attacker already running as the application, and
this module does not pretend otherwise.

**AEAD, not CBC.** Fernet is AES-128-CBC with an HMAC over the ciphertext,
versioned, with the IV and timestamp handled for us. Unauthenticated CBC is
malleable — somebody with write access to the database can alter a ciphertext
undetected — and hand-rolled padding invites padding oracles. Neither risk is
worth the fifty lines saved.

**A missing key fails loudly.** No fallback to a constant, no fallback to
base64 when the library is absent. Both are ways of turning encryption off
without telling anybody, and both have shipped to production elsewhere.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# Marks a value this module produced. Without it there is no way to tell an
# encrypted string from a plaintext one that happens to look like base64 —
# which matters while existing rows are still being migrated, and matters again
# the first time somebody restores an old backup.
PREFIX = "enc:v1:"

# The development default, repeated here so `verify_configured` can recognise
# it. Published and worthless by design: a deployment that forgot to set a real
# key must fail at startup rather than encrypt everything with a string that is
# in the repository.
DEV_KEY = "dev-only-secret-encryption-key-not-for-any-other-use"


class SecretUnavailable(RuntimeError):
    """The key is missing, or the value cannot be decrypted with it.

    Deliberately not a `DomainError`: this is never something a user did. It is
    a deployment that is wrong, and it should surface as a 500 with a log line
    rather than as a polite message suggesting they try again.
    """


def _key() -> bytes:
    """The Fernet key, derived from the configured secret.

    Derived rather than required verbatim so an operator can supply any
    sufficiently long string instead of a base64-encoded 32-byte value — the
    latter is the kind of requirement that gets met by pasting something
    shorter and hoping. SHA-256 gives the exact length Fernet needs from
    whatever was provided.
    """
    raw = settings.secret_encryption_key.get_secret_value().strip()
    if not raw:
        raise SecretUnavailable(
            "SECRET_ENCRYPTION_KEY is not set. Stored credentials cannot be "
            "read or written without it."
        )
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())


def encrypt(value: str) -> str:
    """Encrypt a secret for storage. Empty in, empty out."""
    if not value:
        return ""
    token = Fernet(_key()).encrypt(value.encode()).decode()
    return f"{PREFIX}{token}"


def decrypt(value: str) -> str:
    """Read a stored secret.

    A value without the marker is returned unchanged. That is what lets rows
    written before this module existed keep working while they are migrated,
    and it is deliberately a one-way accommodation: nothing here ever writes
    plaintext.
    """
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value

    try:
        return Fernet(_key()).decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        # Almost always a rotated or mistyped key rather than tampering, but
        # the two are indistinguishable from here and both mean the same thing:
        # this value cannot be trusted or used.
        raise SecretUnavailable(
            "A stored credential could not be decrypted. The encryption key has "
            "probably changed since it was written."
        ) from exc


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)


def verify_configured() -> None:
    """Called at startup. Refuses to run in production without a real key.

    The development default is a published, worthless string on purpose: it
    must be obviously not a secret, so that a deployment which forgot to set
    the real one is caught here rather than by nobody.
    """
    raw = settings.secret_encryption_key.get_secret_value().strip()
    if not raw:
        raise SecretUnavailable("SECRET_ENCRYPTION_KEY is not set.")
    if settings.is_production and raw == DEV_KEY:
        raise SecretUnavailable(
            "SECRET_ENCRYPTION_KEY is still the development default. Set a real "
            "one before running in production."
        )
