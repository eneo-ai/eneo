from __future__ import annotations

import pytest
from pydantic import ValidationError

from eneo.flows.flow_validators_http import validate_authored_http_config
from eneo.flows.http_transport.authored_config import (
    SECRET_SENTINEL,
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBody,
    HttpBodyMode,
)
from eneo.flows.http_transport.errors import HttpTransportError
from eneo.flows.http_transport.validator import validate_authored_config
from eneo.main.exceptions import BadRequestException


def _config(
    *,
    url: str = "https://example.org/api",
    auth=None,
    body: HttpBody | None = None,
    timeout_seconds: int = 30,
) -> HttpAuthoredConfig:
    return HttpAuthoredConfig(
        url=url,
        auth=auth or HttpAuthNone(),
        body=body or HttpBody(mode=HttpBodyMode.AUTO),
        timeout_seconds=timeout_seconds,
    )


def _validate(
    cfg: HttpAuthoredConfig, *, method: str = "POST"
) -> list[HttpTransportError]:
    return validate_authored_config(cfg, direction="output", method=method)


def test_authored_config_model_validate_accepts_json_contract_values() -> None:
    config = HttpAuthoredConfig.model_validate(
        {
            "url": "https://example.org/api",
            "auth": {"mode": "none"},
            "timeout_seconds": 30,
            "custom_headers": [
                {"name": "X-Trace", "value": "trace-id", "secret": False}
            ],
        }
    )

    assert config.timeout_seconds == 30
    assert config.custom_headers[0].secret is False


@pytest.mark.parametrize(
    "payload",
    [
        {
            "url": "https://example.org/api",
            "auth": {"mode": "none"},
            "timeout_seconds": "30",
        },
        {
            "url": "https://example.org/api",
            "auth": {"mode": "none"},
            "timeout_seconds": True,
        },
        {
            "url": "https://example.org/api",
            "auth": {"mode": "none"},
            "custom_headers": [
                {"name": "X-Trace", "value": "trace-id", "secret": "true"}
            ],
        },
    ],
)
def test_authored_config_model_validate_rejects_coerced_json_contract_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        HttpAuthoredConfig.model_validate(payload)


def test_validate_authored_http_config_rejects_coerced_json_contract_values() -> None:
    with pytest.raises(BadRequestException, match="not a valid HTTP config"):
        validate_authored_http_config(
            step_order=1,
            label="output_config",
            config={
                "url": "https://example.org/api",
                "auth": {"mode": "none"},
                "timeout_seconds": "30",
            },
            method="POST",
            direction="output",
        )


# --- URL validation ---


def test_empty_url_returns_missing_url() -> None:
    errors = _validate(_config(url=""))

    assert HttpTransportError.MISSING_URL in errors


def test_whitespace_only_url_returns_missing_url() -> None:
    errors = _validate(_config(url="   "))

    assert HttpTransportError.MISSING_URL in errors


def test_invalid_url_returns_invalid_url() -> None:
    errors = _validate(_config(url="not-a-url"))

    assert HttpTransportError.INVALID_URL in errors


def test_url_without_scheme_returns_invalid_url() -> None:
    errors = _validate(_config(url="example.org/api"))

    assert HttpTransportError.INVALID_URL in errors


def test_url_with_password_userinfo_returns_invalid_url() -> None:
    """Userinfo would store a credential outside the encrypted auth fields."""
    errors = _validate(_config(url="https://user:pass@example.org/api"))

    assert HttpTransportError.INVALID_URL in errors


def test_url_with_username_only_userinfo_returns_invalid_url() -> None:
    errors = _validate(_config(url="https://user@example.org/api"))

    assert HttpTransportError.INVALID_URL in errors


def test_url_with_userinfo_and_a_templated_host_returns_invalid_url() -> None:
    """Userinfo is authored literally; deferring it to interpolation stores it."""
    errors = _validate(_config(url="https://alice:secret@{{host}}/api"))

    assert HttpTransportError.INVALID_URL in errors


def test_at_sign_in_the_path_is_not_userinfo() -> None:
    errors = _validate(_config(url="https://example.org/users/a@b"))

    assert HttpTransportError.INVALID_URL not in errors


def test_template_expression_url_is_validated_after_interpolation() -> None:
    errors = _validate(_config(url="{{base_url}}/api"))

    assert HttpTransportError.MISSING_URL not in errors
    assert HttpTransportError.INVALID_URL not in errors


def test_valid_https_url_no_url_errors() -> None:
    errors = _validate(_config(url="https://example.org/api"))

    assert HttpTransportError.MISSING_URL not in errors
    assert HttpTransportError.INVALID_URL not in errors


def test_valid_http_url_no_url_errors() -> None:
    errors = _validate(_config(url="http://example.org/api"))

    assert HttpTransportError.MISSING_URL not in errors
    assert HttpTransportError.INVALID_URL not in errors


# --- Auth validation ---


def test_bearer_empty_token_returns_missing_auth() -> None:
    errors = _validate(_config(auth=HttpAuthBearer(token="")))

    assert HttpTransportError.MISSING_AUTH_CREDENTIALS in errors


def test_bearer_with_token_no_auth_errors() -> None:
    errors = _validate(_config(auth=HttpAuthBearer(token="tok-123")))

    assert HttpTransportError.MISSING_AUTH_CREDENTIALS not in errors


def test_bearer_with_sentinel_no_auth_errors() -> None:
    cfg = _config(auth=HttpAuthBearer(token=SECRET_SENTINEL))
    errors = _validate(cfg)

    assert HttpTransportError.MISSING_AUTH_CREDENTIALS not in errors


def test_api_key_empty_returns_missing_auth() -> None:
    errors = _validate(_config(auth=HttpAuthApiKey(header_name="X-Key", key="")))

    assert HttpTransportError.MISSING_AUTH_CREDENTIALS in errors


def test_basic_auth_empty_returns_missing_auth() -> None:
    errors = _validate(_config(auth=HttpAuthBasicAuth(username="", password="")))

    assert HttpTransportError.MISSING_AUTH_CREDENTIALS in errors


def test_no_auth_mode_no_auth_errors() -> None:
    errors = _validate(_config(auth=HttpAuthNone()))

    assert HttpTransportError.MISSING_AUTH_CREDENTIALS not in errors


# --- Body validation ---


def test_get_with_body_template_returns_body_not_allowed() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.TEXT_TEMPLATE, template="hello"))
    errors = _validate(cfg, method="GET")

    assert HttpTransportError.BODY_NOT_ALLOWED_FOR_GET in errors


def test_get_with_json_body_returns_body_not_allowed() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template='{"k":"v"}'))
    errors = _validate(cfg, method="GET")

    assert HttpTransportError.BODY_NOT_ALLOWED_FOR_GET in errors


def test_get_with_auto_body_no_body_errors() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.AUTO))
    errors = _validate(cfg, method="GET")

    assert HttpTransportError.BODY_NOT_ALLOWED_FOR_GET not in errors


def test_get_with_none_body_no_body_errors() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.NONE))
    errors = _validate(cfg, method="GET")

    assert HttpTransportError.BODY_NOT_ALLOWED_FOR_GET not in errors


def test_post_with_body_template_no_body_errors() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.TEXT_TEMPLATE, template="hello"))
    errors = _validate(cfg, method="POST")

    assert HttpTransportError.BODY_NOT_ALLOWED_FOR_GET not in errors


def test_invalid_json_template_returns_invalid_body_json() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template="{bad json"))
    errors = _validate(cfg, method="POST")

    assert HttpTransportError.INVALID_BODY_JSON in errors


def test_valid_json_template_no_body_json_errors() -> None:
    cfg = _config(
        body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template='{"key": "val"}')
    )
    errors = _validate(cfg, method="POST")

    assert HttpTransportError.INVALID_BODY_JSON not in errors


def test_template_expressions_in_json_body_are_allowed() -> None:
    cfg = _config(
        body=HttpBody(
            mode=HttpBodyMode.JSON_TEMPLATE,
            template='{"text": "{{step_output}}"}',
        )
    )
    errors = _validate(cfg, method="POST")

    assert HttpTransportError.INVALID_BODY_JSON not in errors


# --- Timeout validation ---


def test_timeout_below_min_returns_out_of_range() -> None:
    errors = _validate(_config(timeout_seconds=0))

    assert HttpTransportError.TIMEOUT_OUT_OF_RANGE in errors


def test_timeout_above_max_returns_out_of_range() -> None:
    errors = _validate(_config(timeout_seconds=999))

    assert HttpTransportError.TIMEOUT_OUT_OF_RANGE in errors


def test_timeout_at_boundary_no_errors() -> None:
    errors_min = _validate(_config(timeout_seconds=1))
    errors_max = _validate(_config(timeout_seconds=120))

    assert HttpTransportError.TIMEOUT_OUT_OF_RANGE not in errors_min
    assert HttpTransportError.TIMEOUT_OUT_OF_RANGE not in errors_max


# --- Valid config ---


def test_valid_config_returns_empty_error_list() -> None:
    cfg = _config(
        url="https://example.org/api",
        auth=HttpAuthBearer(token="tok-123"),
        body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template='{"key": "val"}'),
        timeout_seconds=30,
    )

    errors = _validate(cfg)

    assert errors == []
