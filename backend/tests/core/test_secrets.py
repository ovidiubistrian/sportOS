"""Encrypting what a club hands us.

The properties worth pinning are not "it encrypts" — that is the library's job
— but the three decisions around it: that a missing key stops the application
rather than silently disabling encryption, that values written before the key
existed keep working, and that nothing ever writes plaintext back.
"""

from __future__ import annotations

import pytest

from app.core import secrets as secret_store
from app.core.config import settings

pytestmark = pytest.mark.secrets


class TestRoundTrip:
    def test_a_secret_survives_the_journey(self) -> None:
        token = secret_store.encrypt("bt-gateway-password")

        assert token != "bt-gateway-password"
        assert secret_store.decrypt(token) == "bt-gateway-password"

    def test_an_empty_value_stays_empty(self) -> None:
        """A club with no password stored has no ciphertext either.

        Encrypting "" would produce a token, and `has_password` — which asks
        only whether the field is non-empty — would then report a password
        nobody set.
        """
        assert secret_store.encrypt("") == ""
        assert secret_store.decrypt("") == ""

    def test_the_same_input_encrypts_differently_each_time(self) -> None:
        """Fernet carries its own IV, so identical passwords are not
        recognisable as identical in the database."""
        first = secret_store.encrypt("same")
        second = secret_store.encrypt("same")

        assert first != second
        assert secret_store.decrypt(first) == secret_store.decrypt(second) == "same"


class TestMigrationSafety:
    def test_a_value_written_before_the_key_is_returned_unchanged(self) -> None:
        """The one-way accommodation that lets rows be migrated in place.

        Without it, every club with a gateway configured would break the moment
        this shipped and stay broken until the migration ran.
        """
        assert secret_store.decrypt("plaintext-from-before") == "plaintext-from-before"
        assert not secret_store.is_encrypted("plaintext-from-before")

    def test_encrypted_values_are_recognisable(self) -> None:
        """Which is what makes the migration idempotent: it can tell what it
        has already done."""
        assert secret_store.is_encrypted(secret_store.encrypt("x"))

    def test_a_wrong_key_refuses_rather_than_returning_rubbish(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rotated key must fail loudly.

        Returning a mangled string would send a corrupted password to a bank
        and surface as the bank rejecting the club's credentials — which is a
        support case nobody would trace back to a key change.
        """
        from pydantic import SecretStr

        token = secret_store.encrypt("original")
        monkeypatch.setattr(
            settings, "secret_encryption_key", SecretStr("a-completely-different-key")
        )

        with pytest.raises(secret_store.SecretUnavailable):
            secret_store.decrypt(token)


class TestConfiguration:
    def test_a_missing_key_stops_the_application(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic import SecretStr

        monkeypatch.setattr(settings, "secret_encryption_key", SecretStr(""))

        with pytest.raises(secret_store.SecretUnavailable):
            secret_store.verify_configured()

    def test_the_development_default_is_refused_in_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The published default must not be what protects a club's bank
        credentials. This is the check that catches a deployment which set
        every other secret and forgot this one."""
        from pydantic import SecretStr

        monkeypatch.setattr(settings, "secret_encryption_key", SecretStr(secret_store.DEV_KEY))
        monkeypatch.setattr(settings, "app_env", "production")

        with pytest.raises(secret_store.SecretUnavailable):
            secret_store.verify_configured()

    def test_the_development_default_is_fine_in_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import SecretStr

        monkeypatch.setattr(settings, "secret_encryption_key", SecretStr(secret_store.DEV_KEY))
        monkeypatch.setattr(settings, "app_env", "development")

        secret_store.verify_configured()
