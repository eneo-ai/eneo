import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError

from eneo.files.file_models import FileOriginalNotFoundError
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    EncryptionNotConfiguredException,
    ErrorCodes,
    FileTooLargeException,
)
from eneo.main.models import GeneralError
from eneo.server.exception_handlers import (
    add_exception_handlers,
    is_active_display_name_violation,
)
from eneo.server.main import get_application
from eneo.users.user import PasswordChangeRequest


@pytest.fixture
def password_validation_client() -> TestClient:
    # Exercise the production handler registration without starting a server,
    # database or application lifespan. No credential mutation is performed.
    app = get_application()

    @app.post("/_test-password-validation", status_code=204)
    async def validate_password_request(payload: PasswordChangeRequest):
        return None

    return TestClient(app)


@pytest.mark.parametrize(
    ("payload", "location", "error_type"),
    [
        (
            {"current_password": "current-secret-sentinel"},
            ["body", "new_password"],
            "missing",
        ),
        (
            {"new_password": "new-secret-sentinel"},
            ["body", "current_password"],
            "missing",
        ),
        (
            {
                "current_password": {"value": "current-secret-sentinel"},
                "new_password": "new-secret-sentinel",
            },
            ["body", "current_password"],
            "string_type",
        ),
        (
            {
                "current_password": "current-secret-sentinel",
                "new_password": ["new-secret-sentinel"],
            },
            ["body", "new_password"],
            "string_type",
        ),
        ("current-secret-sentinel", ["body"], "model_attributes_type"),
    ],
)
def test_password_validation_does_not_echo_input(
    password_validation_client: TestClient,
    payload: object,
    location: list[str],
    error_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = password_validation_client.post(
        "/_test-password-validation", json=payload
    )

    assert response.status_code == 422
    body = response.json()
    assert "detail" not in body
    error = body["details"]["errors"][0]
    assert error["location"] == location
    assert error["type"] == error_type
    assert set(error) == {"location", "type", "message"}
    assert "secret-sentinel" not in response.text
    assert "secret-sentinel" not in caplog.text


def test_malformed_password_json_does_not_echo_input(
    password_validation_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = password_validation_client.post(
        "/_test-password-validation",
        content='{"current_password":"current-secret-sentinel", "new_password":',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    error = response.json()["details"]["errors"][0]
    assert error["type"] == "json_invalid"
    assert set(error) == {"location", "type", "message"}
    assert "secret-sentinel" not in response.text
    assert "secret-sentinel" not in caplog.text


def test_validation_does_not_echo_custom_validator_messages() -> None:
    class SensitiveInput(BaseModel):
        password: str

        @field_validator("password")
        @classmethod
        def reject_password(cls, value: str) -> str:
            raise ValueError(f"Rejected password: {value}")

    app = FastAPI()
    add_exception_handlers(app)

    @app.post("/validate")
    async def validate_input(payload: SensitiveInput):
        return None

    response = TestClient(app).post("/validate", json={"password": "secret-sentinel"})

    assert response.status_code == 422
    assert response.json()["details"]["errors"] == [
        {
            "location": ["body", "password"],
            "message": "Invalid value",
            "type": "value_error",
        }
    ]
    assert "secret-sentinel" not in response.text


def test_valid_password_request_reaches_endpoint_without_echoing_secrets(
    password_validation_client: TestClient,
) -> None:
    response = password_validation_client.post(
        "/_test-password-validation",
        json={
            "current_password": "current-secret-sentinel",
            "new_password": "new-secret-sentinel",
        },
    )

    assert response.status_code == 204
    assert response.content == b""


def test_query_validation_preserves_public_field_and_error_type() -> None:
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/items")
    async def items(limit: int):
        return []

    response = TestClient(app).get("/items", params={"limit": "invalid-limit"})

    assert response.status_code == 422
    assert response.json()["details"]["errors"] == [
        {
            "location": ["query", "limit"],
            "message": "Invalid value",
            "type": "int_parsing",
        }
    ]


class _FakeOrig:
    """Stand-in for the DBAPI error wrapped by IntegrityError.orig."""

    def __init__(self, constraint_name=None, text=""):
        if constraint_name is not None:
            self.constraint_name = constraint_name
        self._text = text

    def __str__(self):
        return self._text


def _integrity_error(orig):
    return IntegrityError("INSERT INTO completion_models ...", {}, orig)


class _ValidationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3)


def test_active_nickname_violation_matched_by_constraint_name():
    exc = _integrity_error(
        _FakeOrig(constraint_name="uq_completion_models_active_nickname")
    )
    assert is_active_display_name_violation(exc) is True


def test_active_nickname_violation_matched_by_message_text():
    exc = _integrity_error(
        _FakeOrig(
            text="duplicate key value violates unique constraint "
            '"uq_transcription_models_active_nickname"'
        )
    )
    assert is_active_display_name_violation(exc) is True


def test_other_constraint_not_matched():
    exc = _integrity_error(
        _FakeOrig(
            constraint_name="ck_completion_models_tenant_provider",
            text="violates check constraint",
        )
    )
    assert is_active_display_name_violation(exc) is False


def test_integrity_error_without_orig_not_matched():
    assert is_active_display_name_violation(_integrity_error(None)) is False


def test_active_nickname_violation_maps_to_409():
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/collide")
    async def collide():
        raise _integrity_error(
            _FakeOrig(constraint_name="uq_embedding_models_active_nickname")
        )

    response = TestClient(app).get("/collide")
    assert response.status_code == 409
    error = GeneralError.model_validate(response.json())
    assert error.eneo_error_code == ErrorCodes.NAME_COLLISION
    assert error.code == "name_collision"


def test_file_too_large_exception_includes_structured_details():
    exception = FileTooLargeException(
        file_size=12_582_912,
        max_size=10_485_760,
        limit_name="knowledge_file",
    )

    assert "knowledge_file" in str(exception)
    assert "Storage permission" in str(exception)
    assert exception.details["file_size_bytes"] == 12_582_912
    assert exception.details["max_size_bytes"] == 10_485_760
    assert exception.details["limit_name"] == "knowledge_file"
    assert "docs_hint" not in exception.details


def test_exception_handler_returns_file_size_details_for_413():
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/raise")
    async def raise_exception():
        raise FileTooLargeException(
            file_size=2_048,
            max_size=1_024,
            limit_name="knowledge_file",
        )

    client = TestClient(app)
    response = client.get("/raise")

    assert response.status_code == 413
    body = response.json()
    assert body["eneo_error_code"] == ErrorCodes.FILE_TOO_LARGE
    assert body["details"]["file_size_bytes"] == 2_048
    assert body["details"]["max_size_bytes"] == 1_024
    assert body["details"]["limit_name"] == "knowledge_file"


def test_exception_handler_omits_details_for_exceptions_without_details():
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/bad-request")
    async def bad_request():
        raise BadRequestException("Bad input")

    client = TestClient(app)
    response = client.get("/bad-request")

    assert response.status_code == 400
    body = response.json()
    assert body["message"] == "Bad input"
    assert body["eneo_error_code"] == ErrorCodes.BAD_REQUEST
    assert "details" not in body


def test_exception_handler_returns_conflict_contract():
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/conflict")
    async def conflict():
        raise ConflictException(
            "Runtime file is already attached to a flow run.",
            code="flow_runtime_file_attached",
            context={"file_id": "file-1"},
        )

    client = TestClient(app)
    response = client.get("/conflict")

    assert response.status_code == 409
    body = response.json()
    assert body["message"] == "Runtime file is already attached to a flow run."
    assert body["eneo_error_code"] == ErrorCodes.CONFLICT
    assert body["code"] == "flow_runtime_file_attached"
    assert body["context"] == {"file_id": "file-1"}


def test_request_validation_error_returns_sanitized_general_error():
    app = FastAPI()
    add_exception_handlers(app)

    @app.post("/validate")
    async def validate(payload: _ValidationPayload) -> dict[str, str]:
        return {"name": payload.name}

    response = TestClient(app).post(
        "/validate",
        json={"name": "x", "secret": "submitted-secret"},
        headers={"x-request-id": "request-validation-id"},
    )

    assert response.status_code == 422
    body = response.json()
    error = GeneralError.model_validate(body)
    assert error.message == "Request validation failed."
    assert error.eneo_error_code is ErrorCodes.VALIDATION_ERROR
    assert error.code == "request_validation_error"
    assert error.request_id == "request-validation-id"
    assert "detail" not in body

    errors = body["details"]["errors"]
    assert {
        ("body", "name"),
        ("body", "secret"),
    } <= {tuple(error["location"]) for error in errors}
    assert {"location", "message", "type"} == set(errors[0])
    response_text = response.text
    assert "submitted-secret" not in response_text
    assert "RequestValidationError" not in response_text
    assert '"input"' not in response_text


def test_main_app_request_validation_error_uses_general_error_for_non_flow_route():
    response = TestClient(get_application()).get(
        "/api/healthz/crawler",
        params={"include_all": "not-bool"},
        headers={"x-request-id": "crawler-validation-id"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "Request validation failed."
    assert body["eneo_error_code"] == ErrorCodes.VALIDATION_ERROR
    assert body["code"] == "request_validation_error"
    assert body["request_id"] == "crawler-validation-id"
    assert body["details"]["errors"][0]["location"] == ["query", "include_all"]
    assert "not-bool" not in response.text


async def _allow_test_origin(_origin: str, *_args: object, **_kwargs: object) -> bool:
    # Matches get_origin's (origin, headers, is_preflight, request_url) call.
    return True


def _assert_internal_error_contract(response, *, request_id: str) -> None:
    assert response.status_code == 500
    error = GeneralError.model_validate(response.json())
    assert error.code == "internal_error"
    assert error.eneo_error_code is ErrorCodes.INTERNAL_SERVER_ERROR
    assert error.request_id == request_id
    assert error.error_id is not None
    assert len(error.error_id) == 8
    assert response.headers["x-trace-id"]
    assert response.headers["x-correlation-id"] == response.headers["x-trace-id"]
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "x-trace-id" in exposed
    assert "x-correlation-id" in exposed


def test_explicit_http_500_uses_platform_error_envelope(monkeypatch) -> None:
    monkeypatch.setattr("eneo.server.main.get_origin", _allow_test_origin)
    app = get_application()
    assert app.exception_handlers[500] is app.exception_handlers[Exception]

    @app.get("/_test_explicit_500")
    async def explicit_500() -> None:
        raise HTTPException(status_code=500, detail="must not leak")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/_test_explicit_500",
        headers={"Origin": "http://example.com", "X-Request-ID": "explicit-500"},
    )

    _assert_internal_error_contract(response, request_id="explicit-500")
    assert "must not leak" not in response.text


def test_unhandled_exception_uses_platform_error_envelope(monkeypatch) -> None:
    monkeypatch.setattr("eneo.server.main.get_origin", _allow_test_origin)
    app = get_application()

    @app.get("/_test_unhandled_exception")
    async def unhandled_exception() -> None:
        raise RuntimeError("must not leak")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/_test_unhandled_exception",
        headers={"Origin": "http://example.com", "X-Request-ID": "unhandled-500"},
    )

    _assert_internal_error_contract(response, request_id="unhandled-500")
    assert "must not leak" not in response.text


def test_original_not_found_has_stable_public_contract():
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/original")
    async def original():
        raise FileOriginalNotFoundError()

    response = TestClient(app).get("/original")

    assert response.status_code == 404
    assert response.json()["eneo_error_code"] == ErrorCodes.FILE_ORIGINAL_NOT_FOUND
    assert response.json()["code"] == "file_original_not_found"
    assert response.json()["message"] == (
        "The exact original is not available for this file."
    )


def test_encryption_not_configured_returns_actionable_503_and_logs_it(caplog):
    app = FastAPI()
    add_exception_handlers(app)

    @app.post("/providers")
    async def create_provider():
        raise EncryptionNotConfiguredException(
            "Credential encryption is not configured. Set ENCRYPTION_KEY and "
            "restart the backend."
        )

    with caplog.at_level(logging.ERROR, logger="eneo.server.exception_handlers"):
        response = TestClient(app, raise_server_exceptions=False).post("/providers")

    assert response.status_code == 503
    assert response.json()["eneo_error_code"] == ErrorCodes.ENCRYPTION_NOT_CONFIGURED
    assert response.json()["message"] == (
        "Credential encryption is not configured. Set ENCRYPTION_KEY and restart "
        "the backend."
    )
    assert "POST /providers → 503" in caplog.text
    assert "ENCRYPTION_KEY" in caplog.text


def test_unknown_model_capacity_returns_actionable_http_error():
    from eneo.completion_models.domain.model_capacity import UnknownModelCapacityError

    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/capacity")
    async def capacity():
        raise UnknownModelCapacityError(("max_input_tokens", "max_output_tokens"))

    response = TestClient(app, raise_server_exceptions=False).get("/capacity")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "unknown_model_capacity"
    assert body["context"]["missing_dimensions"] == [
        "max_input_tokens",
        "max_output_tokens",
    ]
    assert "max_input_tokens" in body["message"]
