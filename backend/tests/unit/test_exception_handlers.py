from fastapi import FastAPI
from fastapi.testclient import TestClient

from intric.main.exceptions import (
    BadRequestException,
    FileNotSupportedException,
    FileTooLargeException,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.request_context import clear_request_context, set_request_context
from intric.server.exception_handlers import add_exception_handlers


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
    assert payload["intric_error_code"] == 9001
    assert payload["code"] == "forbidden"
    assert payload["message"] == "Forbidden: you do not have permission to perform this action."
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
    assert payload["intric_error_code"] == 9001
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
    assert payload == {"message": "Not found", "intric_error_code": 9000}


def test_error_handler_sets_request_id_from_headers():
    request_id = "req-123"
    client = _make_client(UnauthorizedException("Denied"))

    response = client.get("/boom", headers={"X-Correlation-ID": request_id})

    assert response.status_code == 403
    payload = response.json()
    assert payload["request_id"] == request_id


def test_error_handler_sets_request_id_from_x_request_id_header():
    request_id = "req-header-456"
    client = _make_client(UnauthorizedException("Denied"))

    response = client.get("/boom", headers={"X-Request-ID": request_id})

    assert response.status_code == 403
    payload = response.json()
    assert payload["request_id"] == request_id


def test_error_handler_sets_request_id_from_request_context_fallback():
    client = _make_client(UnauthorizedException("Denied"))
    set_request_context(correlation_id="ctx-correlation-id")

    try:
        response = client.get("/boom")
    finally:
        clear_request_context()

    assert response.status_code == 403
    payload = response.json()
    assert payload["request_id"] == "ctx-correlation-id"


def test_bad_request_exception_with_code_exposes_machine_readable_contract():
    client = _make_client(
        BadRequestException(
            "Flow must be published before creating runs.",
            code="flow_not_published",
            context={"flow_id": "flow-123"},
        )
    )

    response = client.get("/boom")

    assert response.status_code == 400
    payload = response.json()
    assert payload["intric_error_code"] == 9007
    assert payload["code"] == "flow_not_published"
    assert payload["message"] == "Flow must be published before creating runs."
    assert payload["context"]["flow_id"] == "flow-123"


def test_file_not_supported_exception_with_code_exposes_machine_readable_contract():
    client = _make_client(
        FileNotSupportedException(
            "Unsupported file type for this flow.",
            code="unsupported_media_type",
            context={"flow_id": "flow-123", "received_mimetype": "application/pdf"},
        )
    )

    response = client.get("/boom")

    assert response.status_code == 415
    payload = response.json()
    assert payload["intric_error_code"] == 9014
    assert payload["code"] == "unsupported_media_type"
    assert payload["message"] == "Unsupported file type for this flow."
    assert payload["context"] == {
        "flow_id": "flow-123",
        "received_mimetype": "application/pdf",
    }


def test_file_too_large_exception_with_code_exposes_machine_readable_contract():
    client = _make_client(
        FileTooLargeException(
            "Uploaded file exceeds effective flow max size limit.",
            code="file_too_large",
            context={"flow_id": "flow-123", "max_file_size_bytes": 25000000},
        )
    )

    response = client.get("/boom")

    assert response.status_code == 413
    payload = response.json()
    assert payload["intric_error_code"] == 9015
    assert payload["code"] == "file_too_large"
    assert payload["message"] == "Uploaded file exceeds effective flow max size limit."
    assert payload["context"] == {
        "flow_id": "flow-123",
        "max_file_size_bytes": 25000000,
    }


def test_non_auth_error_context_strips_auth_layer():
    client = _make_client(
        BadRequestException(
            "Invalid payload",
            code="invalid_payload",
            context={"auth_layer": "jwt", "field": "payload"},
        )
    )

    response = client.get("/boom")

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "invalid_payload"
    assert payload["context"] == {"field": "payload"}


def test_non_auth_error_context_strips_auth_layer_key():
    client = _make_client(
        BadRequestException(
            "Invalid input.",
            code="flow_invalid",
            context={"auth_layer": "api_key", "flow_id": "flow-1"},
        )
    )

    response = client.get("/boom")

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "flow_invalid"
    assert payload["context"] == {"flow_id": "flow-1"}
