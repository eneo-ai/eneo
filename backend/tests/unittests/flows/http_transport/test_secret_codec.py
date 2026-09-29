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
    merge_secrets_on_update,
    protect_authored_secrets,
    redact_authored_config,
    redact_persisted_config,
    secret_fields_holding_templates,
    templated_secret_fields,
    templated_step_credentials,
    unresolved_secret_sentinel_fields,
)
from eneo.flows.variable_resolver import iter_template_expressions
from eneo.main.exceptions import BadRequestException


@dataclass
class _FakeEncryption:
    """Fake encryption service using a reversible prefix scheme."""

    prefix: str = "ENC:"

    def is_active(self) -> bool:
        return True

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(self.prefix)

    def can_decrypt(self, value: str) -> bool:
        return value.startswith(self.prefix)

    def encrypt(self, plaintext: str) -> str:
        return f"{self.prefix}{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext[len(self.prefix) :]


@dataclass
class _OpaqueEncryption(_FakeEncryption):
    """Ciphertext that shows nothing of the plaintext, as real ciphertext does."""

    def encrypt(self, plaintext: str) -> str:
        return f"{self.prefix}{plaintext[::-1]}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext[len(self.prefix) :][::-1]


@dataclass
class _InactiveEncryption:
    """No key configured. Ciphertext is still recognizable by its prefix."""

    prefix: str = "ENC:"

    def is_active(self) -> bool:
        return False

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(self.prefix)

    def can_decrypt(self, value: str) -> bool:
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


# --- protect_authored_secrets ---


def test_protect_encrypts_bearer_token() -> None:
    cfg = _config(auth=HttpAuthBearer(token="my-token"))

    result = protect_authored_secrets(cfg, _FakeEncryption())

    assert result.auth.token == "ENC:my-token"


def test_protect_encrypts_api_key() -> None:
    cfg = _config(auth=HttpAuthApiKey(header_name="X-Key", key="secret"))

    result = protect_authored_secrets(cfg, _FakeEncryption())

    assert result.auth.key == "ENC:secret"
    assert result.auth.header_name == "X-Key"  # header name NOT encrypted


def test_protect_encrypts_basic_auth_password() -> None:
    cfg = _config(auth=HttpAuthBasicAuth(username="alice", password="pass"))

    result = protect_authored_secrets(cfg, _FakeEncryption())

    assert result.auth.password == "ENC:pass"
    assert result.auth.username == "alice"  # username NOT encrypted


def test_protect_encrypts_secret_custom_headers_only() -> None:
    cfg = _config(
        custom_headers=[
            CustomHeader(name="X-Secret", value="secret-val", secret=True),
            CustomHeader(name="X-Public", value="public-val", secret=False),
        ]
    )

    result = protect_authored_secrets(cfg, _FakeEncryption())

    assert result.custom_headers[0].value == "ENC:secret-val"
    assert result.custom_headers[1].value == "public-val"


def test_protect_encrypts_authored_value_wearing_the_encryption_prefix() -> None:
    """The prefix is authored syntax; it must never suppress encryption."""
    cfg = _config(auth=HttpAuthBearer(token="ENC:not-really-encrypted"))

    result = protect_authored_secrets(cfg, _FakeEncryption())

    assert result.auth.token == "ENC:ENC:not-really-encrypted"


def test_protect_leaves_stored_secret_sentinel_for_the_caller_to_resolve() -> None:
    cfg = _config(auth=HttpAuthBearer(token=SECRET_SENTINEL))

    result = protect_authored_secrets(cfg, _FakeEncryption())

    assert result.auth.token == SECRET_SENTINEL


# --- protect_authored_secrets: refusal when encryption is unavailable ---


@pytest.mark.parametrize(
    ("auth", "expected_field"),
    [
        (HttpAuthBearer(token="my-token"), "auth.token"),
        (HttpAuthApiKey(header_name="X-Key", key="my-key"), "auth.key"),
        (HttpAuthBasicAuth(username="alice", password="my-pass"), "auth.password"),
    ],
)
def test_protect_refuses_covers_each_auth_mode_when_inactive(
    auth: HttpAuthBearer | HttpAuthApiKey | HttpAuthBasicAuth,
    expected_field: str,
) -> None:
    cfg = _config(auth=auth)

    with pytest.raises(AuthoredSecretEncryptionUnavailableError) as excinfo:
        protect_authored_secrets(cfg, _InactiveEncryption())

    assert excinfo.value.secret_fields == (expected_field,)


def test_protect_refuses_when_no_encryption_service_at_all() -> None:
    cfg = _config(auth=HttpAuthBearer(token="my-token"))

    with pytest.raises(AuthoredSecretEncryptionUnavailableError) as excinfo:
        protect_authored_secrets(cfg, None)

    assert excinfo.value.secret_fields == ("auth.token",)
    assert "my-token" not in str(excinfo.value)


def test_protect_refuses_does_not_trust_the_encryption_prefix_as_provenance() -> None:
    """An author can type the prefix; it is syntax, not proof of ciphertext."""
    cfg = _config(auth=HttpAuthBearer(token="enc:fernet:v1:not-really-encrypted"))

    with pytest.raises(AuthoredSecretEncryptionUnavailableError) as excinfo:
        protect_authored_secrets(cfg, _InactiveEncryption())

    assert excinfo.value.secret_fields == ("auth.token",)


def test_protect_refuses_identifies_secret_headers_by_index_not_author_supplied_name() -> (
    None
):
    cfg = _config(
        custom_headers=[
            CustomHeader(name="X-Public", value="public-val", secret=False),
            CustomHeader(name="X-Secret", value="secret-val", secret=True),
        ]
    )

    with pytest.raises(AuthoredSecretEncryptionUnavailableError) as excinfo:
        protect_authored_secrets(cfg, _InactiveEncryption())

    assert excinfo.value.secret_fields == ("custom_headers[1].value",)


def test_protect_refuses_allows_secret_free_config_when_inactive() -> None:
    cfg = _config(
        auth=HttpAuthNone(),
        custom_headers=[CustomHeader(name="X-Public", value="public", secret=False)],
    )

    protect_authored_secrets(cfg, _InactiveEncryption())


def test_protect_refuses_allows_stored_secret_sentinel_when_inactive() -> None:
    """A sentinel references an existing row; it is not a newly authored value."""
    cfg = _config(auth=HttpAuthBearer(token=SECRET_SENTINEL))

    protect_authored_secrets(cfg, _InactiveEncryption())


# --- unresolved_secret_sentinel_fields ---


def test_unresolved_sentinel_fields_reports_sentinels_left_after_merge() -> None:
    cfg = _config(
        auth=HttpAuthBearer(token=SECRET_SENTINEL),
        custom_headers=[
            CustomHeader(name="X-Secret", value=SECRET_SENTINEL, secret=True)
        ],
    )

    assert unresolved_secret_sentinel_fields(cfg) == (
        "auth.token",
        "custom_headers[0].value",
    )


def test_unresolved_sentinel_fields_ignores_resolved_values() -> None:
    cfg = _config(auth=HttpAuthBearer(token="ENC:stored"))

    assert unresolved_secret_sentinel_fields(cfg) == ()


def test_unresolved_sentinel_fields_covers_non_secret_headers() -> None:
    """A sentinel resolved to nothing whatever the incoming secret flag says."""
    cfg = _config(
        custom_headers=[
            CustomHeader(name="X-Public", value=SECRET_SENTINEL, secret=False)
        ]
    )

    assert unresolved_secret_sentinel_fields(cfg) == ("custom_headers[0].value",)


# --- redact_persisted_config ---


def test_redact_persisted_config_turns_stored_secrets_into_sentinels() -> None:
    stored = _config(
        auth=HttpAuthBearer(token="ENC:stored"),
        custom_headers=[
            CustomHeader(name="X-Secret", value="ENC:hdr", secret=True),
            CustomHeader(name="X-Public", value="public", secret=False),
        ],
    ).model_dump(mode="json")

    result = redact_persisted_config(stored)

    assert result is not None
    assert result["auth"]["token"] == SECRET_SENTINEL
    assert result["custom_headers"][0]["value"] == SECRET_SENTINEL
    assert result["custom_headers"][1]["value"] == "public"


def test_redact_persisted_config_passes_through_non_authored_payloads() -> None:
    assert redact_persisted_config(None) is None
    assert redact_persisted_config({"template_asset_id": "abc"}) == {
        "template_asset_id": "abc"
    }


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


# --- Credentials that hold templates ---


def test_secret_fields_holding_templates_names_declared_secret_fields_only() -> None:
    config = HttpAuthoredConfig(
        url="https://example.org/{{ step_1.output.text }}",
        auth=HttpAuthApiKey(header_name="X-{{ a }}", key="{{ flow_input.key }}"),
        custom_headers=[
            CustomHeader(name="X-Open", value="{{ step_1.output.text }}"),
            CustomHeader(name="X-Ok", value="literal", secret=True),
            CustomHeader(name="X-Bad", value="{{ datum }}", secret=True),
        ],
        body=HttpBody(mode=HttpBodyMode.TEXT_TEMPLATE, template="{{ b }}"),
    )

    assert secret_fields_holding_templates(config) == (
        "auth.key",
        "custom_headers[2].value",
    )


def test_secret_fields_holding_templates_ignores_literals_and_stored_secrets() -> None:
    config = HttpAuthoredConfig(
        url="https://example.org",
        auth=HttpAuthBearer(token="Bearer {single} and {{ unclosed"),
        custom_headers=[CustomHeader(name="X-S", value=SECRET_SENTINEL, secret=True)],
    )

    assert secret_fields_holding_templates(config) == ()


def _parsed(payload: dict[str, object]) -> HttpAuthoredConfig:
    return HttpAuthoredConfig.model_validate(payload)


def test_templated_secret_fields_reads_the_decrypted_credential() -> None:
    encryption = _OpaqueEncryption()
    persisted = _parsed(
        {
            "url": "https://example.org",
            "auth": {
                "mode": "bearer_token",
                "token": encryption.encrypt("{{ step_1.output.text }}"),
            },
            "custom_headers": [
                {
                    "name": "X-Ok",
                    "value": encryption.encrypt("literal"),
                    "secret": True,
                },
            ],
        }
    )
    assert not iter_template_expressions(persisted.auth.token)  # pyright: ignore[reportAttributeAccessIssue]

    assert templated_secret_fields(persisted, encryption) == ("auth.token",)
    assert (
        templated_secret_fields(
            _parsed({"auth": {"mode": "none"}, "url": "x"}), encryption
        )
        == ()
    )


def test_templated_secret_fields_reads_a_plaintext_credential_as_stored() -> None:
    persisted = _parsed(
        {
            "url": "https://example.org",
            "auth": {"mode": "bearer_token", "token": "{{ step_1.output.text }}"},
        }
    )

    assert templated_secret_fields(persisted, None) == ("auth.token",)
    assert templated_secret_fields(persisted, _InactiveEncryption()) == ("auth.token",)


def test_templated_secret_fields_leaves_what_the_key_cannot_decrypt() -> None:
    class _KeyLost(_OpaqueEncryption):
        def can_decrypt(self, value: str) -> bool:
            return False

        def decrypt(self, ciphertext: str) -> str:
            raise AssertionError("must not decrypt what the key cannot open")

    persisted = _parsed(
        {
            "url": "https://example.org",
            "auth": {
                "mode": "bearer_token",
                "token": _OpaqueEncryption().encrypt("{{ step_1.output.text }}"),
            },
        }
    )

    assert templated_secret_fields(persisted, _KeyLost()) == ()


def _templated_config() -> dict[str, object]:
    return {
        "url": "https://example.org",
        "auth": {"mode": "bearer_token", "token": "{{ step_1.output.text }}"},
    }


def test_templated_step_credentials_reads_the_config_of_the_mode_the_step_runs() -> (
    None
):
    encryption = _OpaqueEncryption()

    def credentials(**fields: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return templated_step_credentials(
            **{
                "step_order": 1,
                "input_source": "previous_step",
                "output_mode": "pass_through",
                "input_config": None,
                "output_config": None,
                **fields,
            },  # pyright: ignore[reportArgumentType]
            encryption_service=encryption,
        )

    assert credentials(input_source="http_get", input_config=_templated_config()) == (
        ("input_config", ("auth.token",)),
    )
    assert credentials(output_mode="http_post", output_config=_templated_config()) == (
        ("output_config", ("auth.token",)),
    )
    assert credentials(
        input_source="http_get",
        input_config=_templated_config(),
        output_mode="http_post",
        output_config=_templated_config(),
    ) == (("input_config", ("auth.token",)), ("output_config", ("auth.token",)))
    # Configuration of a mode the step does not run is never sent.
    assert credentials(input_config=_templated_config()) == ()
    assert credentials(output_config=_templated_config()) == ()


def test_templated_step_credentials_names_the_step_and_field_of_an_unreadable_config() -> (
    None
):
    with pytest.raises(BadRequestException) as excinfo:
        templated_step_credentials(
            step_order=3,
            input_source="previous_step",
            output_mode="http_post",
            input_config=None,
            output_config={
                "url": "https://example.org",
                "auth": {"mode": "bogus", "token": "s3cret-value"},
            },
            encryption_service=_OpaqueEncryption(),
        )

    error = excinfo.value
    assert error.code == "typed_io_http_invalid_config"
    assert "Step 3" in str(error)
    assert "output_config.auth" in str(error)
    assert "bogus" not in str(error)
    assert "s3cret-value" not in str(error)
    assert error.__cause__ is None
    assert error.context == {
        "issue_code": "flow_step_invalid",
        "step_order": 3,
        "field": "output_config.auth",
    }


def test_templated_step_credentials_does_not_read_a_config_of_a_mode_not_run() -> None:
    # Only what is sent has to parse: the input config of a step that is not
    # http_get is another reader's.
    assert (
        templated_step_credentials(
            step_order=1,
            input_source="previous_step",
            output_mode="pass_through",
            input_config={"auth": {"mode": "bogus"}},
            output_config=None,
            encryption_service=_OpaqueEncryption(),
        )
        == ()
    )


_VALID_URL = "https://example.org/hook"


@pytest.mark.parametrize(
    ("kind", "config", "field"),
    [
        pytest.param(
            "http_post", {"url": _VALID_URL}, "output_config", id="missing-auth"
        ),
        pytest.param(
            "http_post",
            {"url": _VALID_URL, "auth": {"mode": "bogus"}},
            "output_config.auth",
            id="bogus-auth-mode",
        ),
        pytest.param(
            "http_post",
            {"url": _VALID_URL, "auth": {"mode": "none"}, "timeout_seconds": "soon"},
            "output_config.timeout_seconds",
            id="timeout-not-a-number",
        ),
        pytest.param(
            "http_post",
            {"url": _VALID_URL, "auth": {"mode": "none"}, "unknown": 1},
            "output_config.unknown",
            id="unknown-key",
        ),
        pytest.param(
            "http_get",
            {"url": "not a url", "auth": {"mode": "none"}},
            "input_config.url",
            id="malformed-url",
        ),
        pytest.param(
            "http_get",
            {"url": "ftp://example.org/x", "auth": {"mode": "none"}},
            "input_config.url",
            id="unsupported-scheme",
        ),
        pytest.param(
            "http_get",
            {"url": "  ", "auth": {"mode": "none"}},
            "input_config.url",
            id="empty-url",
        ),
        pytest.param(
            "http_get",
            {
                "url": "https://alice:secret@{{ flow_input.host }}/lookup",
                "auth": {"mode": "none"},
            },
            "input_config.url",
            id="templated-userinfo",
        ),
        pytest.param(
            "http_get",
            {
                "url": "ftp://example.org/{{ flow_input.id }}",
                "auth": {"mode": "none"},
            },
            "input_config.url",
            id="fixed-non-http-scheme-before-a-template",
        ),
        pytest.param("http_get", None, "input_config", id="http_get-without-config"),
        pytest.param(
            "http_get", {"url": _VALID_URL}, "input_config", id="http_get-missing-auth"
        ),
    ],
)
def test_templated_step_credentials_refuses_any_config_the_runtime_would_not_accept(
    kind: str, config: dict[str, object] | None, field: str
) -> None:
    fields: dict[str, object] = (
        {"input_source": "http_get", "input_config": config}
        if kind == "http_get"
        else {"output_mode": "http_post", "output_config": config}
    )

    with pytest.raises(BadRequestException) as excinfo:
        templated_step_credentials(
            **{
                "step_order": 2,
                "input_source": "previous_step",
                "output_mode": "pass_through",
                "input_config": None,
                "output_config": None,
                **fields,
            },  # pyright: ignore[reportArgumentType]
            encryption_service=_OpaqueEncryption(),
        )

    error = excinfo.value
    assert error.code == "typed_io_http_invalid_config"
    assert str(error).startswith("Step 2: ")
    assert field in str(error)
    assert error.context["step_order"] == 2
    assert error.context["field"] == field
    assert error.context["issue_code"] == "flow_step_invalid"
    assert "not a url" not in str(error)
    assert "alice:secret" not in str(error)


def test_templated_step_credentials_reads_a_fixed_url_only_once_it_is_known() -> None:
    def credentials(url: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return templated_step_credentials(
            step_order=1,
            input_source="http_get",
            output_mode="pass_through",
            input_config={"url": url, "auth": {"mode": "none"}},
            output_config=None,
            encryption_service=_OpaqueEncryption(),
        )

    # A URL with a template is checked once it is filled, at the request.
    assert credentials("https://{{ flow_input.host }}/lookup") == ()
    assert credentials("https://example.org/{{ flow_input.id }}") == ()
    assert credentials("{{ flow_input.url }}") == ()
    assert credentials("https://example.org/lookup") == ()


def test_templated_step_credentials_accepts_a_webhook_without_config() -> None:
    # The runtime sends nothing for it, so there is nothing to refuse.
    assert (
        templated_step_credentials(
            step_order=1,
            input_source="previous_step",
            output_mode="http_post",
            input_config=None,
            output_config=None,
            encryption_service=_OpaqueEncryption(),
        )
        == ()
    )
