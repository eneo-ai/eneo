from __future__ import annotations


from intric.flows.http_transport.authored_config import (
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBody,
    HttpBodyMode,
)
from intric.flows.http_transport.errors import HttpTransportError
from intric.flows.http_transport.secret_codec import SECRET_SENTINEL
from intric.flows.http_transport.validator import validate_authored_config


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


def _validate(cfg: HttpAuthoredConfig, *, method: str = "POST") -> list[HttpTransportError]:
    return validate_authored_config(cfg, direction="output", method=method)


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
    # Sentinel is a dict injected via model_copy, same as redact_authored_config does
    auth = HttpAuthBearer(token="placeholder").model_copy(update={"token": SECRET_SENTINEL})
    cfg = _config(auth=auth)
    errors = _validate(cfg)

    assert HttpTransportError.MISSING_AUTH_CREDENTIALS not in errors


def test_api_key_empty_returns_missing_auth() -> None:
    errors = _validate(_config(auth=HttpAuthApiKey(header_name="X-Key", key="")))

    assert HttpTransportError.MISSING_AUTH_CREDENTIALS in errors


def test_basic_auth_empty_returns_missing_auth() -> None:
    errors = _validate(
        _config(auth=HttpAuthBasicAuth(username="", password=""))
    )

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
    cfg = _config(body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template='{"key": "val"}'))
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
