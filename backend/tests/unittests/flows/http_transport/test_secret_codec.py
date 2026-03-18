from __future__ import annotations

from dataclasses import dataclass


from intric.flows.http_transport.authored_config import (
    CustomHeader,
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBody,
    HttpBodyMode,
)
from intric.flows.http_transport.secret_codec import (
    SECRET_SENTINEL,
    decrypt_authored_config,
    encrypt_authored_config,
    merge_secrets_on_update,
    redact_authored_config,
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
    def is_active(self) -> bool:
        return False

    def is_encrypted(self, value: str) -> bool:
        return False

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


# --- merge_secrets_on_update ---


def _with_sentinel(auth_model, field: str):
    """Inject sentinel dict into an auth model via model_copy (bypasses Pydantic str validation)."""
    return auth_model.model_copy(update={field: SECRET_SENTINEL})


def test_merge_sentinel_preserves_stored_bearer_token() -> None:
    incoming_auth = _with_sentinel(HttpAuthBearer(token="placeholder"), "token")
    incoming = _config(auth=incoming_auth)
    stored = _config(auth=HttpAuthBearer(token="ENC:stored-token"))

    result = merge_secrets_on_update(incoming, stored)

    assert result.auth.token == "ENC:stored-token"


def test_merge_new_value_passes_through_for_bearer() -> None:
    incoming = _config(auth=HttpAuthBearer(token="new-plain-token"))
    stored = _config(auth=HttpAuthBearer(token="ENC:stored-token"))

    result = merge_secrets_on_update(incoming, stored)

    assert result.auth.token == "new-plain-token"


def test_merge_sentinel_preserves_stored_api_key() -> None:
    incoming_auth = _with_sentinel(HttpAuthApiKey(header_name="X-Key", key="placeholder"), "key")
    incoming = _config(auth=incoming_auth)
    stored = _config(auth=HttpAuthApiKey(header_name="X-Key", key="ENC:stored-key"))

    result = merge_secrets_on_update(incoming, stored)

    assert result.auth.key == "ENC:stored-key"


def test_merge_sentinel_preserves_stored_basic_auth_password() -> None:
    incoming_auth = _with_sentinel(
        HttpAuthBasicAuth(username="alice", password="placeholder"), "password"
    )
    incoming = _config(auth=incoming_auth)
    stored = _config(
        auth=HttpAuthBasicAuth(username="alice", password="ENC:stored-pass")
    )

    result = merge_secrets_on_update(incoming, stored)

    assert result.auth.password == "ENC:stored-pass"


def test_merge_sentinel_preserves_stored_secret_custom_header() -> None:
    incoming = _config(
        custom_headers=[CustomHeader(name="X-Secret", value=SECRET_SENTINEL, secret=True)]
    )
    stored = _config(
        custom_headers=[CustomHeader(name="X-Secret", value="ENC:stored-val", secret=True)]
    )

    result = merge_secrets_on_update(incoming, stored)

    assert result.custom_headers[0].value == "ENC:stored-val"


def test_merge_new_custom_header_value_passes_through() -> None:
    incoming = _config(
        custom_headers=[CustomHeader(name="X-Secret", value="new-val", secret=True)]
    )
    stored = _config(
        custom_headers=[CustomHeader(name="X-Secret", value="ENC:stored-val", secret=True)]
    )

    result = merge_secrets_on_update(incoming, stored)

    assert result.custom_headers[0].value == "new-val"
