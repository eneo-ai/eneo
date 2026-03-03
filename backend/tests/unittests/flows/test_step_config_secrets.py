from __future__ import annotations

from typing import Any

import pytest

from intric.flows.step_config_secrets import (
    decrypt_step_headers_for_runtime,
    encrypt_step_headers_for_storage,
)
from intric.main.exceptions import BadRequestException


class _EncryptionService:
    _PREFIX = "enc:fernet:v1:"

    def is_active(self) -> bool:
        return True

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(self._PREFIX)

    def encrypt(self, plaintext: str) -> str:
        return f"{self._PREFIX}{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        if ciphertext.startswith(self._PREFIX):
            return ciphertext[len(self._PREFIX):]
        return ciphertext


class _InactiveEncryptionService(_EncryptionService):
    def is_active(self) -> bool:
        return False


def test_encrypt_headers_returns_none_for_none_config():
    assert encrypt_step_headers_for_storage(config=None, encryption_service=None) is None


def test_encrypt_headers_skips_non_object_headers():
    config: dict[str, Any] = {"url": "https://example.org", "headers": "not-an-object"}
    result = encrypt_step_headers_for_storage(config=config, encryption_service=None)
    assert result == config


def test_encrypt_headers_allows_empty_headers_without_encryption_service():
    config: dict[str, Any] = {"url": "https://example.org", "headers": {}}
    result = encrypt_step_headers_for_storage(config=config, encryption_service=None)
    assert result == config


def test_encrypt_headers_requires_active_encryption_for_non_empty_headers():
    config: dict[str, Any] = {"url": "https://example.org", "headers": {"Authorization": "Bearer secret"}}
    with pytest.raises(BadRequestException, match="ENCRYPTION_KEY"):
        encrypt_step_headers_for_storage(config=config, encryption_service=None)


def test_encrypt_headers_rejects_inactive_encryption_service_for_non_empty_headers():
    config: dict[str, Any] = {"url": "https://example.org", "headers": {"Authorization": "Bearer secret"}}
    with pytest.raises(BadRequestException, match="ENCRYPTION_KEY"):
        encrypt_step_headers_for_storage(
            config=config,
            encryption_service=_InactiveEncryptionService(),
        )


def test_encrypt_headers_encrypts_plaintext_and_keeps_non_string_values():
    config: dict[str, Any] = {
        "url": "https://example.org",
        "headers": {
            "Authorization": "Bearer top-secret",
            "X-Trace": "enc:fernet:v1:already",
            "X-Retries": 2,
        },
    }
    result = encrypt_step_headers_for_storage(config=config, encryption_service=_EncryptionService())
    headers = result["headers"]
    assert headers["Authorization"] == "enc:fernet:v1:Bearer top-secret"
    assert headers["X-Trace"] == "enc:fernet:v1:already"
    assert headers["X-Retries"] == 2


def test_decrypt_headers_decrypts_only_encrypted_values():
    config: dict[str, Any] = {
        "url": "https://example.org",
        "headers": {
            "Authorization": "enc:fernet:v1:Bearer top-secret",
            "X-Plain": "visible",
            "X-Retries": 2,
        },
    }
    result = decrypt_step_headers_for_runtime(config=config, encryption_service=_EncryptionService())
    headers = result["headers"]
    assert headers["Authorization"] == "Bearer top-secret"
    assert headers["X-Plain"] == "visible"
    assert headers["X-Retries"] == 2


def test_decrypt_headers_returns_original_config_without_encryption_service():
    config: dict[str, Any] = {"url": "https://example.org", "headers": {"Authorization": "enc:fernet:v1:abc"}}
    result = decrypt_step_headers_for_runtime(config=config, encryption_service=None)
    assert result == config


def test_decrypt_headers_skips_non_object_headers():
    config: dict[str, Any] = {"url": "https://example.org", "headers": "not-an-object"}
    result = decrypt_step_headers_for_runtime(config=config, encryption_service=_EncryptionService())
    assert result == config
