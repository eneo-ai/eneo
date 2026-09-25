"""
Unit tests for EncryptionService initialization in Container.

This test suite verifies the fix for the bug where EncryptionService.is_active()
returned False even when ENCRYPTION_KEY was set in environment variables.

Root Cause:
-----------
The Container defined:
    encryption_service = providers.Singleton(
        EncryptionService,
        encryption_key=config.settings.encryption_key,  # ← Provider chain, never resolved
    )

The `config` provider was never populated with actual values, so
`config.settings.encryption_key` resolved to None at runtime.

Fix:
----
Changed to use get_settings() directly:
    encryption_service = providers.Singleton(
        EncryptionService,
        encryption_key=get_settings().encryption_key,  # ← Direct value
    )
"""

import os
from unittest.mock import patch

import pytest

from eneo.main.container.container import Container
from eneo.main.exceptions import EncryptionNotConfiguredException
from eneo.settings.encryption_service import EncryptionService


class TestEncryptionServiceInitialization:
    """Test that EncryptionService is properly initialized in Container."""

    def test_encryption_service_active_when_key_set(self):
        """Test EncryptionService is active when ENCRYPTION_KEY is set."""
        # Arrange: Set encryption key in environment
        test_key = "FNVdDyfq0lBPAvjz_WS-9PB2UQzkbqCnwuA4KU9UbPU="  # Valid Fernet key

        with patch.dict(
            os.environ,
            {
                "ENCRYPTION_KEY": test_key,
                "TENANT_CREDENTIALS_ENABLED": "true",
            },
            clear=False,  # Keep other env vars
        ):
            # Need to reload settings module to pick up new env vars
            from importlib import reload

            from eneo.main import config

            reload(config)

            # Act: Create container (mimics what happens in API requests)
            container = Container()
            encryption_service = container.encryption_service()

            # Assert: Service should be active
            assert encryption_service.is_active(), (
                "EncryptionService.is_active() returned False despite ENCRYPTION_KEY being set. "
                "This likely means the Container is using the provider chain (config.settings.encryption_key) "
                "instead of the direct value (get_settings().encryption_key)."
            )

            # Verify it actually works
            test_secret = "sk-test-key-12345"
            encrypted = encryption_service.encrypt(test_secret)
            decrypted = encryption_service.decrypt(encrypted)
            assert decrypted == test_secret

    def test_decrypt_allows_plaintext_when_disabled(self):
        """Plaintext passthrough remains available when encryption is disabled."""
        service = EncryptionService(None)

        assert service.decrypt("sk-legacy-plaintext") == "sk-legacy-plaintext"

    def test_decrypt_encrypted_value_without_key_raises_configuration_error(self):
        configured_service = EncryptionService(
            "FNVdDyfq0lBPAvjz_WS-9PB2UQzkbqCnwuA4KU9UbPU="
        )
        ciphertext = configured_service.encrypt("sk-test-key")

        with pytest.raises(EncryptionNotConfiguredException, match="ENCRYPTION_KEY"):
            EncryptionService(None).decrypt(ciphertext)

    def test_encryption_service_inactive_when_initialized_without_key(self):
        """Test EncryptionService is inactive when initialized without a key."""
        # Create service directly without key
        service = EncryptionService(None)

        # Assert: Service should be inactive
        assert not service.is_active()

    def test_encrypt_without_key_raises_typed_configuration_error(self):
        service = EncryptionService(None)

        with pytest.raises(EncryptionNotConfiguredException) as exc_info:
            service.encrypt("sk-test-key")

        assert str(exc_info.value) == (
            "Credential encryption is not configured. Set ENCRYPTION_KEY and "
            "restart the backend."
        )

    def test_encryption_service_fails_on_invalid_fernet_key(self):
        """Test EncryptionService raises a typed error with an invalid Fernet key."""
        with pytest.raises(
            EncryptionNotConfiguredException,
            match="ENCRYPTION_KEY is invalid",
        ):
            EncryptionService("invalid-not-base64-fernet-key")


# Regression test metadata
__test_metadata__ = {
    "bug_id": "encryption-service-is-active-false",
    "fixed_date": "2025-10-07",
    "fixed_by": "Claude Code",
    "root_cause": "Container used unpopulated provider chain (config.settings.encryption_key)",
    "fix": "Changed to direct value (get_settings().encryption_key)",
    "related_files": [
        "backend/src/eneo/main/container/container.py",
        "backend/src/eneo/settings/encryption_service.py",
        "backend/src/eneo/tenants/tenant_repo.py",
    ],
}
