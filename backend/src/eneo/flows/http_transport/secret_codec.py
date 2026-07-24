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
from eneo.flows.http_transport.errors import AuthoredSecretEncryptionUnavailableError


class SupportsEncryption(Protocol):
    def is_active(self) -> bool: ...
    def is_encrypted(self, value: str) -> bool: ...
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


def authored_secret_fields(config: HttpAuthoredConfig) -> tuple[str, ...]:
    """Name the declared secret fields holding a newly authored value.

    A stored-secret sentinel is a reference to an existing row, not a value, so
    it does not count. Everything else that is a non-empty string is new authored
    input.

    The encryption prefix is deliberately not consulted: it is authored syntax,
    not proof of provenance. An author can type ``enc:fernet:v1:...`` into a
    token field, and treating that as ciphertext would let an unprotected
    credential through. Only the caller knows whether a value came from an
    author or from storage.
    """

    def _is_authored_value(value: SecretValue) -> bool:
        return isinstance(value, str) and bool(value)

    fields: list[str] = []
    match config.auth:
        case HttpAuthBearer(token=token):
            if _is_authored_value(token):
                fields.append("auth.token")
        case HttpAuthApiKey(key=key):
            if _is_authored_value(key):
                fields.append("auth.key")
        case HttpAuthBasicAuth(password=password):
            if _is_authored_value(password):
                fields.append("auth.password")
        case HttpAuthNone():
            pass

    fields.extend(
        f"custom_headers[{index}].value"
        for index, header in enumerate(config.custom_headers)
        if header.secret and _is_authored_value(header.value)
    )
    return tuple(fields)


def unresolved_secret_sentinel_fields(config: HttpAuthoredConfig) -> tuple[str, ...]:
    """Name the declared secret fields still holding a sentinel.

    After stored secrets have been merged, a remaining sentinel resolved to
    nothing: it references a stored value that does not exist. Persisting it
    would store the sentinel itself as the credential.
    """
    fields: list[str] = []
    match config.auth:
        case HttpAuthBearer(token=token):
            if is_secret_sentinel(token):
                fields.append("auth.token")
        case HttpAuthApiKey(key=key):
            if is_secret_sentinel(key):
                fields.append("auth.key")
        case HttpAuthBasicAuth(password=password):
            if is_secret_sentinel(password):
                fields.append("auth.password")
        case HttpAuthNone():
            pass

    fields.extend(
        f"custom_headers[{index}].value"
        for index, header in enumerate(config.custom_headers)
        if header.secret and is_secret_sentinel(header.value)
    )
    return tuple(fields)


def protect_authored_secrets(
    config: HttpAuthoredConfig,
    encryption_service: SupportsEncryption | None,
) -> HttpAuthoredConfig:
    """Encrypt newly authored secrets, or refuse when they cannot be protected.

    Call this with author-supplied config, before stored-secret sentinels are
    merged. Provenance only exists here: afterwards a secret may legitimately be
    ciphertext loaded from the existing row, and syntax cannot tell the two
    apart.

    Sentinels pass through for the caller to resolve. Every other non-empty
    declared secret is new authored input and is encrypted unconditionally — an
    author can type ``enc:fernet:v1:`` into a token field, so the prefix is never
    accepted as evidence that a value is already ciphertext.

    Raises:
        AuthoredSecretEncryptionUnavailableError: encryption is unavailable and
            the config carries at least one newly authored secret.
    """
    if encryption_service is None or not encryption_service.is_active():
        unprotectable = authored_secret_fields(config)
        if unprotectable:
            raise AuthoredSecretEncryptionUnavailableError(unprotectable)
        return config

    def _encrypt(value: SecretValue) -> SecretValue:
        if not isinstance(value, str) or not value:
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
