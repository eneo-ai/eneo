from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from eneo.flows.api.flow_http_test_models import (
    HTTP_TEST_REQUEST_EXAMPLE,
    HTTP_TEST_RESPONSE_EXAMPLE,
    HttpTestRequest,
    HttpTestResponse,
)
from eneo.flows.http_transport import HttpAuthoredConfig, HttpTransportError


def _http_test_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "config": {
            "url": "https://example.org/api",
            "auth": {"mode": "none"},
            "body": {"mode": "auto"},
            "custom_headers": [],
            "timeout_seconds": 30,
        },
        "direction": "output",
        "method": "POST",
        "test_variables": {"name": "Alex"},
    }
    payload.update(overrides)
    return payload


def _assert_extra_forbidden(model: type[BaseModel], payload: dict[str, object]) -> None:
    with_extra = {**payload, "unexpected_field": "not allowed"}

    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(with_extra)

    assert any(error["type"] == "extra_forbidden" for error in exc_info.value.errors())


def _assert_example_keys_belong_to_model(
    *, model: type[BaseModel], example: dict[str, object]
) -> None:
    assert set(example) <= set(model.model_fields)


def test_http_test_request_example_matches_public_model() -> None:
    _assert_example_keys_belong_to_model(
        model=HttpTestRequest,
        example=HTTP_TEST_REQUEST_EXAMPLE,
    )

    request = HttpTestRequest.model_validate(HTTP_TEST_REQUEST_EXAMPLE)

    assert request.direction == "output"
    assert request.method == "POST"
    assert isinstance(request.config, HttpAuthoredConfig)


def test_http_test_response_example_matches_public_model() -> None:
    _assert_example_keys_belong_to_model(
        model=HttpTestResponse,
        example=HTTP_TEST_RESPONSE_EXAMPLE,
    )

    response = HttpTestResponse.model_validate(HTTP_TEST_RESPONSE_EXAMPLE)

    assert response.success is True
    assert response.status_code == 200


def test_http_test_request_rejects_unknown_top_level_fields() -> None:
    _assert_extra_forbidden(HttpTestRequest, _http_test_payload())


def test_http_test_request_keeps_nested_maps_open() -> None:
    request = HttpTestRequest.model_validate(
        _http_test_payload(
            test_variables={"case": {"nested": True}},
        )
    )

    assert request.test_variables == {"case": {"nested": True}}


def test_http_test_request_accepts_current_payload_shape() -> None:
    request = HttpTestRequest.model_validate(_http_test_payload())

    assert request.direction == "output"
    assert request.method == "POST"
    assert request.test_variables == {"name": "Alex"}


def test_http_test_request_rejects_unknown_config_fields() -> None:
    with pytest.raises(ValidationError):
        HttpTestRequest.model_validate(
            _http_test_payload(
                config={
                    "url": "https://example.org/api",
                    "auth": {"mode": "none"},
                    "body": {"mode": "auto"},
                    "custom_headers": [],
                    "timeout_seconds": 30,
                    "unknown": {"nested": True},
                }
            )
        )


def test_http_test_request_rejects_unknown_method() -> None:
    with pytest.raises(ValidationError):
        HttpTestRequest.model_validate(_http_test_payload(method="DELETE"))


def test_http_test_response_parses_current_payload_shape() -> None:
    response = HttpTestResponse.model_validate(
        {
            "success": False,
            "status_code": None,
            "duration_ms": 12.5,
            "response_preview": None,
            "request_preview": {
                "method": "POST",
                "url": "https://example.org/api",
                "headers": {},
                "body_preview": None,
            },
            "error_code": "HTTP_INVALID_URL",
            "error_message": "bad config",
        }
    )

    assert response.success is False
    assert response.error_code == HttpTransportError.INVALID_URL


def test_http_test_response_rejects_unknown_error_code() -> None:
    with pytest.raises(ValidationError):
        HttpTestResponse.model_validate(
            {
                "success": False,
                "request_preview": None,
                "error_code": "NOT_A_REAL_HTTP_TEST_ERROR",
            }
        )


def test_http_test_response_rejects_incomplete_request_preview() -> None:
    with pytest.raises(ValidationError):
        HttpTestResponse.model_validate(
            {
                "success": False,
                "request_preview": {"method": "POST"},
                "error_code": "HTTP_INVALID_URL",
            }
        )
