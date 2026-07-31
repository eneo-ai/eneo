import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from eneo.main.exceptions import (
    EXCEPTION_MAP,
    BadRequestException,
    ErrorCodes,
    NotFoundException,
    OpenAIException,
    ProviderRejectedRequestException,
    UnauthorizedException,
)
from eneo.main.models import GeneralError
from eneo.server.exception_handlers import add_exception_handlers

EXPECTED_DERIVED_ERROR_CODES = frozenset(
    {
        "api_key_not_configured",
        "authentication_error",
        "bad_request",
        "chunk_embedding_mismatch",
        "claude_error",
        "conflict",
        "crawl_already_running",
        "encryption_not_configured",
        "file_corrupt",
        "file_encrypted",
        "file_extraction_error",
        "file_format_unsupported",
        "file_not_supported",
        "file_too_large",
        "iam_exception",
        "internal_http_error",
        "internal_server_error",
        "knowledge_model_unavailable",
        "mcp_upstream_auth_error",
        "mcp_upstream_error",
        "model_in_use",
        "model_not_available",
        "name_collision",
        "no_model_selected",
        "not_found",
        "openai_error",
        "provider_inactive",
        "provider_not_found",
        "provider_rejected_request",
        "provisioning_not_enabled",
        "pydantic_parse_error",
        "query_error",
        "quota_exceeded",
        "resource_gone",
        "resource_not_ready",
        "security_classification_mismatch",
        "skill_revision_conflict",
        "system_user_protected",
        "tenant_suspended",
        "unauthorized",
        "unique_error",
        "unique_user_error",
        "unsupported_model",
        "user_inactive",
        "user_not_created",
        "validation_error",
    }
)


def _make_client(exc_to_raise: Exception) -> TestClient:
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise exc_to_raise

    return TestClient(app)


def test_unauthorized_exception_without_message_has_readable_default():
    client = _make_client(UnauthorizedException())

    response = client.get("/boom")

    assert response.status_code == 403
    payload = response.json()
    assert payload["eneo_error_code"] == 9001
    assert payload["code"] == "forbidden"
    assert (
        payload["message"]
        == "Forbidden: you do not have permission to perform this action."
    )
    assert payload["context"]["auth_layer"] == "domain_policy"
    assert "request_id" not in payload


def test_unauthorized_exception_with_message_preserves_domain_reason():
    expected = "Publishing assistants is not allowed for your current space role."
    client = _make_client(
        UnauthorizedException(
            expected,
            code="forbidden_action",
            context={"resource_type": "assistant", "action": "publish"},
        )
    )

    response = client.get("/boom")

    assert response.status_code == 403
    payload = response.json()
    assert payload["eneo_error_code"] == 9001
    assert payload["code"] == "forbidden_action"
    assert payload["message"] == expected
    assert payload["context"]["resource_type"] == "assistant"
    assert payload["context"]["action"] == "publish"
    assert payload["context"]["auth_layer"] == "domain_policy"


def test_error_handler_excludes_null_optional_fields():
    client = _make_client(NotFoundException())

    response = client.get("/boom")

    assert response.status_code == 404
    payload = response.json()
    assert payload == {
        "message": "Not found",
        "eneo_error_code": 9000,
        "code": "not_found",
    }


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/boom",
            "raw_path": b"/boom",
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


@pytest.mark.parametrize(
    ("exception_type", "expected_error_code"),
    [(exception_type, mapping[2]) for exception_type, mapping in EXCEPTION_MAP.items()],
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_every_mapped_exception_has_stable_fallback_code(
    exception_type: type[Exception], expected_error_code: ErrorCodes
) -> None:
    app = FastAPI()
    add_exception_handlers(app)
    handler = app.exception_handlers[exception_type]

    response = handler(_request(), Exception("mapped failure"))
    payload = json.loads(response.body)
    error = GeneralError.model_validate(payload)

    assert error.code == expected_error_code.name.lower()
    assert error.eneo_error_code is expected_error_code


def test_derived_error_code_vocabulary_is_stable() -> None:
    derived_codes = {mapping[2].name.lower() for mapping in EXCEPTION_MAP.values()}

    assert derived_codes == EXPECTED_DERIVED_ERROR_CODES


@pytest.mark.parametrize("instance_code", ["", " ", "\t\n"])
def test_mapped_exception_treats_blank_instance_code_as_absent(
    instance_code: str,
) -> None:
    client = _make_client(BadRequestException("Bad input", code=instance_code))

    response = client.get("/boom")

    assert response.status_code == 400
    assert GeneralError.model_validate(response.json()).code == "bad_request"


def test_error_handler_sets_request_id_from_headers():
    request_id = "req-123"
    client = _make_client(UnauthorizedException("Denied"))

    response = client.get("/boom", headers={"X-Correlation-ID": request_id})

    assert response.status_code == 403
    payload = response.json()
    assert payload["request_id"] == request_id


def test_openai_exception_preserves_structured_provider_error_for_api_clients():
    client = _make_client(
        OpenAIException(
            "AI service is temporarily unavailable. Please try again later.",
            code="provider_unavailable",
            details={"reason": "provider_unavailable", "retryable": True},
        )
    )

    response = client.get("/boom")

    assert response.status_code == 503
    payload = response.json()
    assert payload["message"] == (
        "AI service is temporarily unavailable. Please try again later."
    )
    assert payload["eneo_error_code"] == ErrorCodes.OPENAI_ERROR
    assert payload["code"] == "provider_unavailable"
    assert payload["details"] == {
        "reason": "provider_unavailable",
        "retryable": True,
    }


def test_provider_rejected_request_maps_to_400_despite_openai_subclassing():
    client = _make_client(
        ProviderRejectedRequestException(
            "The AI provider rejected the request.",
            code="provider_rejected_request",
            details={"reason": "provider_rejected_request", "retryable": False},
        )
    )

    response = client.get("/boom")

    assert response.status_code == 400
    payload = response.json()
    assert payload["eneo_error_code"] == ErrorCodes.PROVIDER_REJECTED_REQUEST
    assert payload["code"] == "provider_rejected_request"
    assert payload["details"]["retryable"] is False
