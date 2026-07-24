from __future__ import annotations

from dataclasses import dataclass

import pytest

from eneo.flows.http_transport.authored_config import (
    SECRET_SENTINEL,
    CustomHeader,
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBody,
    HttpBodyMode,
)
from eneo.flows.http_transport.errors import AuthoredSecretEncryptionUnavailableError
from eneo.flows.http_transport.secret_codec import (
    decrypt_authored_config,
    encrypt_authored_config,
    merge_secrets_on_update,
    redact_authored_config,
    reject_unprotectable_authored_secrets,
)


@dataclass
class _FakeEncryption:
    """Fake encryption service using a reversible prefix scheme."""

    prefix: str = "ENC:"

    def is_active(self) -> bool:
        return True

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(self.prefix)

    def encrypt(self, plaintext: str) -> str:
        return f"{self.prefix}{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext[len(self.prefix) :]


@dataclass
class _InactiveEncryption:
    """No key configured. Ciphertext is still recognizable by its prefix."""

    prefix: str = "ENC:"

    def is_active(self) -> bool:
        return False

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(self.prefix)

    def encrypt(self, plaintext: str) -> str:
        raise AssertionError("should not be called")

    def decrypt(self, ciphertext: str) -> str:
        raise AssertionError("should not be called")


def _config(
    *,
    auth=None,
    custom_headers: list[CustomHeader] | None = None,
) -> HttpAuthoredConfig:
    return HttpAuthoredConfig(
        url="https://example.org/api",
        auth=auth or HttpAuthNone(),
        body=HttpBody(mode=HttpBodyMode.AUTO),
        custom_headers=custom_headers or [],
        timeout_seconds=30,
    )


# --- encrypt_authored_config ---


def test_encrypt_bearer_token() -> None:
    cfg = _config(auth=HttpAuthBearer(token="my-token"))
    enc = _FakeEncryption()

    result = encrypt_authored_config(cfg, enc)

    assert result.auth.token == "ENC:my-token"


def test_encrypt_api_key() -> None:
    cfg = _config(auth=HttpAuthApiKey(header_name="X-Key", key="secret"))
    enc = _FakeEncryption()

    result = encrypt_authored_config(cfg, enc)

    assert result.auth.key == "ENC:secret"
    assert result.auth.header_name == "X-Key"  # header name NOT encrypted


def test_encrypt_basic_auth_password() -> None:
    cfg = _config(auth=HttpAuthBasicAuth(username="alice", password="pass"))
    enc = _FakeEncryption()

    result = encrypt_authored_config(cfg, enc)

    assert result.auth.password == "ENC:pass"
    assert result.auth.username == "alice"  # username NOT encrypted


def test_encrypt_secret_custom_headers() -> None:
    headers = [
        CustomHeader(name="X-Secret", value="secret-val", secret=True),
        CustomHeader(name="X-Public", value="public-val", secret=False),
    ]
    cfg = _config(custom_headers=headers)
    enc = _FakeEncryption()

    result = encrypt_authored_config(cfg, enc)

    assert result.custom_headers[0].value == "ENC:secret-val"
    assert result.custom_headers[1].value == "public-val"  # non-secret untouched


def test_encrypt_skips_already_encrypted_values() -> None:
    cfg = _config(auth=HttpAuthBearer(token="ENC:already"))
    enc = _FakeEncryption()

    result = encrypt_authored_config(cfg, enc)

    assert result.auth.token == "ENC:already"  # not double-encrypted


def test_encrypt_with_none_service_returns_unchanged() -> None:
    cfg = _config(auth=HttpAuthBearer(token="my-token"))

    result = encrypt_authored_config(cfg, None)

    assert result.auth.token == "my-token"


def test_encrypt_with_inactive_service_returns_unchanged() -> None:
    cfg = _config(auth=HttpAuthBearer(token="my-token"))

    result = encrypt_authored_config(cfg, _InactiveEncryption())

    assert result.auth.token == "my-token"


# --- reject_unprotectable_authored_secrets ---


@pytest.mark.parametrize(
    ("auth", "expected_field"),
    [
        (HttpAuthBearer(token="my-token"), "auth.token"),
        (HttpAuthApiKey(header_name="X-Key", key="my-key"), "auth.key"),
        (HttpAuthBasicAuth(username="alice", password="my-pass"), "auth.password"),
    ],
)
def test_reject_covers_each_auth_mode_when_inactive(
    auth: HttpAuthBearer | HttpAuthApiKey | HttpAuthBasicAuth,
    expected_field: str,
) -> None:
    cfg = _config(auth=auth)

    with pytest.raises(AuthoredSecretEncryptionUnavailableError) as excinfo:
        reject_unprotectable_authored_secrets(cfg, _InactiveEncryption())

    assert excinfo.value.secret_fields == (expected_field,)


def test_reject_when_no_encryption_service_at_all() -> None:
    cfg = _config(auth=HttpAuthBearer(token="my-token"))

    with pytest.raises(AuthoredSecretEncryptionUnavailableError) as excinfo:
        reject_unprotectable_authored_secrets(cfg, None)

    assert excinfo.value.secret_fields == ("auth.token",)
    assert "my-token" not in str(excinfo.value)


def test_reject_does_not_trust_the_encryption_prefix_as_provenance() -> None:
    """An author can type the prefix; it is syntax, not proof of ciphertext."""
    cfg = _config(auth=HttpAuthBearer(token="enc:fernet:v1:not-really-encrypted"))

    with pytest.raises(AuthoredSecretEncryptionUnavailableError) as excinfo:
        reject_unprotectable_authored_secrets(cfg, _InactiveEncryption())

    assert excinfo.value.secret_fields == ("auth.token",)


def test_reject_identifies_secret_headers_by_index_not_author_supplied_name() -> None:
    cfg = _config(
        custom_headers=[
            CustomHeader(name="X-Public", value="public-val", secret=False),
            CustomHeader(name="X-Secret", value="secret-val", secret=True),
        ]
    )

    with pytest.raises(AuthoredSecretEncryptionUnavailableError) as excinfo:
        reject_unprotectable_authored_secrets(cfg, _InactiveEncryption())

    assert excinfo.value.secret_fields == ("custom_headers[1].value",)


def test_reject_allows_secret_free_config_when_inactive() -> None:
    cfg = _config(
        auth=HttpAuthNone(),
        custom_headers=[CustomHeader(name="X-Public", value="public", secret=False)],
    )

    reject_unprotectable_authored_secrets(cfg, _InactiveEncryption())


def test_reject_allows_stored_secret_sentinel_when_inactive() -> None:
    """A sentinel references an existing row; it is not a newly authored value."""
    cfg = _config(auth=HttpAuthBearer(token=SECRET_SENTINEL))

    reject_unprotectable_authored_secrets(cfg, _InactiveEncryption())


def test_reject_is_a_noop_when_encryption_is_active() -> None:
    cfg = _config(auth=HttpAuthBearer(token="my-token"))

    reject_unprotectable_authored_secrets(cfg, _FakeEncryption())


# --- decrypt_authored_config ---


def test_decrypt_bearer_token() -> None:
    cfg = _config(auth=HttpAuthBearer(token="ENC:my-token"))
    enc = _FakeEncryption()

    result = decrypt_authored_config(cfg, enc)

    assert result.auth.token == "my-token"


def test_decrypt_api_key() -> None:
    cfg = _config(auth=HttpAuthApiKey(header_name="X-Key", key="ENC:secret"))
    enc = _FakeEncryption()

    result = decrypt_authored_config(cfg, enc)

    assert result.auth.key == "secret"


def test_decrypt_basic_auth_password() -> None:
    cfg = _config(auth=HttpAuthBasicAuth(username="alice", password="ENC:pass"))
    enc = _FakeEncryption()

    result = decrypt_authored_config(cfg, enc)

    assert result.auth.password == "pass"


def test_decrypt_secret_custom_headers() -> None:
    headers = [
        CustomHeader(name="X-Secret", value="ENC:secret-val", secret=True),
        CustomHeader(name="X-Public", value="public-val", secret=False),
    ]
    cfg = _config(custom_headers=headers)
    enc = _FakeEncryption()

    result = decrypt_authored_config(cfg, enc)

    assert result.custom_headers[0].value == "secret-val"
    assert result.custom_headers[1].value == "public-val"


def test_decrypt_with_none_service_returns_unchanged() -> None:
    cfg = _config(auth=HttpAuthBearer(token="ENC:my-token"))

    result = decrypt_authored_config(cfg, None)

    assert result.auth.token == "ENC:my-token"


def test_decrypt_skips_non_encrypted_values() -> None:
    cfg = _config(auth=HttpAuthBearer(token="plain-text"))
    enc = _FakeEncryption()

    result = decrypt_authored_config(cfg, enc)

    assert result.auth.token == "plain-text"


def test_authored_config_accepts_bearer_secret_sentinel_wire_shape() -> None:
    config = HttpAuthoredConfig.model_validate(
        {
            "url": "https://example.org/api",
            "auth": {"mode": "bearer_token", "token": SECRET_SENTINEL},
            "timeout_seconds": 30,
        }
    )

    assert config.auth.token == SECRET_SENTINEL
    assert config.model_dump(mode="json")["auth"]["token"] == SECRET_SENTINEL


def test_authored_config_accepts_api_key_secret_sentinel_wire_shape() -> None:
    config = HttpAuthoredConfig.model_validate(
        {
            "url": "https://example.org/api",
            "auth": {
                "mode": "api_key",
                "header_name": "X-Key",
                "key": SECRET_SENTINEL,
            },
            "timeout_seconds": 30,
        }
    )

    assert config.auth.key == SECRET_SENTINEL
    assert config.model_dump(mode="json")["auth"]["key"] == SECRET_SENTINEL


def test_authored_config_accepts_basic_auth_secret_sentinel_wire_shape() -> None:
    config = HttpAuthoredConfig.model_validate(
        {
            "url": "https://example.org/api",
            "auth": {
                "mode": "basic_auth",
                "username": "alice",
                "password": SECRET_SENTINEL,
            },
            "timeout_seconds": 30,
        }
    )

    assert config.auth.password == SECRET_SENTINEL
    assert config.model_dump(mode="json")["auth"]["password"] == SECRET_SENTINEL


# --- redact_authored_config ---


def test_redact_bearer_token() -> None:
    cfg = _config(auth=HttpAuthBearer(token="my-token"))

    result = redact_authored_config(cfg)

    assert result.auth.token == SECRET_SENTINEL


def test_redact_api_key() -> None:
    cfg = _config(auth=HttpAuthApiKey(header_name="X-Key", key="secret"))

    result = redact_authored_config(cfg)

    assert result.auth.key == SECRET_SENTINEL
    assert result.auth.header_name == "X-Key"


def test_redact_basic_auth_password() -> None:
    cfg = _config(auth=HttpAuthBasicAuth(username="alice", password="pass"))

    result = redact_authored_config(cfg)

    assert result.auth.password == SECRET_SENTINEL
    assert result.auth.username == "alice"


def test_redact_secret_custom_headers() -> None:
    headers = [
        CustomHeader(name="X-Secret", value="secret-val", secret=True),
        CustomHeader(name="X-Public", value="public-val", secret=False),
    ]
    cfg = _config(custom_headers=headers)

    result = redact_authored_config(cfg)

    assert result.custom_headers[0].value == SECRET_SENTINEL
    assert result.custom_headers[1].value == "public-val"


def test_redact_no_auth_leaves_config_unchanged() -> None:
    cfg = _config(auth=HttpAuthNone())

    result = redact_authored_config(cfg)

    assert result.url == cfg.url
    assert result.auth.mode == "none"


def test_merge_sentinel_preserves_stored_bearer_token() -> None:
    incoming = HttpAuthoredConfig.model_validate(
        {
            "url": "https://example.org/api",
            "auth": {"mode": "bearer_token", "token": SECRET_SENTINEL},
            "timeout_seconds": 30,
        }
    )
    stored = _config(auth=HttpAuthBearer(token="ENC:stored-token"))

    result = merge_secrets_on_update(incoming, stored)

    assert result.auth.token == "ENC:stored-token"


def test_merge_new_value_passes_through_for_bearer() -> None:
    incoming = _config(auth=HttpAuthBearer(token="new-plain-token"))
    stored = _config(auth=HttpAuthBearer(token="ENC:stored-token"))

    result = merge_secrets_on_update(incoming, stored)

    assert result.auth.token == "new-plain-token"


def test_merge_sentinel_preserves_stored_api_key() -> None:
    incoming = HttpAuthoredConfig.model_validate(
        {
            "url": "https://example.org/api",
            "auth": {
                "mode": "api_key",
                "header_name": "X-Key",
                "key": SECRET_SENTINEL,
            },
            "timeout_seconds": 30,
        }
    )
    stored = _config(auth=HttpAuthApiKey(header_name="X-Key", key="ENC:stored-key"))

    result = merge_secrets_on_update(incoming, stored)

    assert result.auth.key == "ENC:stored-key"


def test_merge_sentinel_preserves_stored_basic_auth_password() -> None:
    incoming = HttpAuthoredConfig.model_validate(
        {
            "url": "https://example.org/api",
            "auth": {
                "mode": "basic_auth",
                "username": "alice",
                "password": SECRET_SENTINEL,
            },
            "timeout_seconds": 30,
        }
    )
    stored = _config(
        auth=HttpAuthBasicAuth(username="alice", password="ENC:stored-pass")
    )

    result = merge_secrets_on_update(incoming, stored)

    assert result.auth.password == "ENC:stored-pass"


def test_merge_sentinel_preserves_stored_secret_custom_header() -> None:
    incoming = _config(
        custom_headers=[
            CustomHeader(name="X-Secret", value=SECRET_SENTINEL, secret=True)
        ]
    )
    stored = _config(
        custom_headers=[
            CustomHeader(name="X-Secret", value="ENC:stored-val", secret=True)
        ]
    )

    result = merge_secrets_on_update(incoming, stored)

    assert result.custom_headers[0].value == "ENC:stored-val"


def test_merge_new_custom_header_value_passes_through() -> None:
    incoming = _config(
        custom_headers=[CustomHeader(name="X-Secret", value="new-val", secret=True)]
    )
    stored = _config(
        custom_headers=[
            CustomHeader(name="X-Secret", value="ENC:stored-val", secret=True)
        ]
    )

    result = merge_secrets_on_update(incoming, stored)

    assert result.custom_headers[0].value == "new-val"
