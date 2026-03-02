from __future__ import annotations

from typing import Any, Protocol

from intric.main.exceptions import BadRequestException


class SupportsEncryption(Protocol):
    def is_active(self) -> bool: ...
    def is_encrypted(self, value: str) -> bool: ...
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


def encrypt_step_headers_for_storage(
    *,
    config: dict[str, Any] | None,
    encryption_service: SupportsEncryption | None,
) -> dict[str, Any] | None:
    if config is None:
        return config

    headers = config.get("headers")
    if not isinstance(headers, dict):
        return config
    if headers and (encryption_service is None or not encryption_service.is_active()):
        raise BadRequestException(
            "Webhook headers require active encryption. Configure ENCRYPTION_KEY before saving header secrets."
        )

    encrypted_headers: dict[str, Any] = {}
    for key, value in headers.items():
        if not isinstance(value, str):
            encrypted_headers[key] = value
            continue
        encrypted_headers[key] = (
            value
            if encryption_service.is_encrypted(value)
            else encryption_service.encrypt(value)
        )

    next_config = dict(config)
    next_config["headers"] = encrypted_headers
    return next_config


def decrypt_step_headers_for_runtime(
    *,
    config: dict[str, Any] | None,
    encryption_service: SupportsEncryption | None,
) -> dict[str, Any] | None:
    if config is None or encryption_service is None:
        return config

    headers = config.get("headers")
    if not isinstance(headers, dict):
        return config

    decrypted_headers: dict[str, Any] = {}
    for key, value in headers.items():
        if not isinstance(value, str):
            decrypted_headers[key] = value
            continue
        decrypted_headers[key] = (
            encryption_service.decrypt(value)
            if encryption_service.is_encrypted(value)
            else value
        )

    next_config = dict(config)
    next_config["headers"] = decrypted_headers
    return next_config
