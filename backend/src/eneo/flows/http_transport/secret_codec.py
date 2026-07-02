from __future__ import annotations

from typing import Protocol

from eneo.flows.http_transport.authored_config import (
    SECRET_SENTINEL,
    CustomHeader,
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    SecretValue,
    is_secret_sentinel,
)


class SupportsEncryption(Protocol):
    def is_active(self) -> bool: ...
    def is_encrypted(self, value: str) -> bool: ...
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


def encrypt_authored_config(
    config: HttpAuthoredConfig,
    encryption_service: SupportsEncryption | None,
) -> HttpAuthoredConfig:
    """Encrypt sensitive fields for database storage."""
    if encryption_service is None or not encryption_service.is_active():
        return config

    def _encrypt(value: SecretValue) -> SecretValue:
        if not isinstance(value, str) or not value:
            return value
        if encryption_service.is_encrypted(value):
            return value
        return encryption_service.encrypt(value)

    auth = config.auth
    match auth:
        case HttpAuthBearer(token=token):
            auth = auth.model_copy(update={"token": _encrypt(token)})
        case HttpAuthApiKey(key=key):
            auth = auth.model_copy(update={"key": _encrypt(key)})
        case HttpAuthBasicAuth(password=pwd):
            auth = auth.model_copy(update={"password": _encrypt(pwd)})
        case HttpAuthNone():
            pass

    custom_headers = [
        h.model_copy(update={"value": _encrypt(h.value)}) if h.secret else h
        for h in config.custom_headers
    ]

    return config.model_copy(update={"auth": auth, "custom_headers": custom_headers})


def decrypt_authored_config(
    config: HttpAuthoredConfig,
    encryption_service: SupportsEncryption | None,
) -> HttpAuthoredConfig:
    """Decrypt sensitive fields for runtime execution."""
    if encryption_service is None:
        return config

    def _decrypt(value: SecretValue) -> SecretValue:
        if not isinstance(value, str):
            return value
        if not value:
            return value
        if encryption_service.is_encrypted(value):
            return encryption_service.decrypt(value)
        return value

    auth = config.auth
    match auth:
        case HttpAuthBearer(token=token):
            auth = auth.model_copy(update={"token": _decrypt(token)})
        case HttpAuthApiKey(key=key):
            auth = auth.model_copy(update={"key": _decrypt(key)})
        case HttpAuthBasicAuth(password=pwd):
            auth = auth.model_copy(update={"password": _decrypt(pwd)})
        case HttpAuthNone():
            pass

    custom_headers = [
        h.model_copy(update={"value": _decrypt(h.value)}) if h.secret else h
        for h in config.custom_headers
    ]

    return config.model_copy(update={"auth": auth, "custom_headers": custom_headers})


def redact_authored_config(config: HttpAuthoredConfig) -> HttpAuthoredConfig:
    """Replace sensitive fields with sentinel for API responses."""
    auth = config.auth
    match auth:
        case HttpAuthBearer():
            auth = auth.model_copy(update={"token": SECRET_SENTINEL})
        case HttpAuthApiKey():
            auth = auth.model_copy(update={"key": SECRET_SENTINEL})
        case HttpAuthBasicAuth():
            auth = auth.model_copy(update={"password": SECRET_SENTINEL})
        case HttpAuthNone():
            pass

    custom_headers = [
        h.model_copy(update={"value": SECRET_SENTINEL}) if h.secret else h
        for h in config.custom_headers
    ]

    return config.model_copy(update={"auth": auth, "custom_headers": custom_headers})


def merge_secrets_on_update(
    incoming: HttpAuthoredConfig,
    stored: HttpAuthoredConfig,
) -> HttpAuthoredConfig:
    """Preserve stored encrypted values when incoming field contains sentinel.

    If the incoming field equals the sentinel, the stored encrypted value is kept.
    If the incoming field is a new plain-text value, it passes through for encryption.
    """

    def _merge_field(
        incoming_value: SecretValue,
        stored_value: SecretValue,
    ) -> SecretValue:
        if is_secret_sentinel(incoming_value):
            return stored_value
        return incoming_value

    auth = incoming.auth
    match incoming.auth, stored.auth:
        case HttpAuthBearer() as inc, HttpAuthBearer() as sto:
            auth = inc.model_copy(update={"token": _merge_field(inc.token, sto.token)})
        case HttpAuthApiKey() as inc, HttpAuthApiKey() as sto:
            auth = inc.model_copy(update={"key": _merge_field(inc.key, sto.key)})
        case HttpAuthBasicAuth() as inc, HttpAuthBasicAuth() as sto:
            auth = inc.model_copy(
                update={"password": _merge_field(inc.password, sto.password)}
            )
        case _:
            pass

    stored_headers_by_name = {h.name: h for h in stored.custom_headers}
    merged_headers: list[CustomHeader] = []
    for h in incoming.custom_headers:
        if h.secret and is_secret_sentinel(h.value):
            stored_h = stored_headers_by_name.get(h.name)
            if stored_h is not None:
                merged_headers.append(h.model_copy(update={"value": stored_h.value}))
            else:
                merged_headers.append(h)
        else:
            merged_headers.append(h)

    return incoming.model_copy(update={"auth": auth, "custom_headers": merged_headers})
