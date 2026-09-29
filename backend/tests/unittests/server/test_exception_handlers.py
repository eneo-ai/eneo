import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError

from eneo.files.file_models import FileOriginalNotFoundError
from eneo.main.exceptions import (
    BadRequestException,
    EncryptionNotConfiguredException,
    ErrorCodes,
    FileTooLargeException,
)
from eneo.server.exception_handlers import (
    add_exception_handlers,
    is_active_display_name_violation,
)
from eneo.users.user import PasswordChangeRequest


@pytest.fixture
def password_validation_client() -> TestClient:
    # Exercise the production handler registration without starting a server,
    # database or application lifespan. No credential mutation is performed.
    from eneo.server.main import get_application

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
    detail = response.json()["detail"][0]
    assert detail["loc"] == location
    assert detail["type"] == error_type
    assert set(detail) == {"loc", "type", "msg"}
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
    assert response.json()["detail"][0]["type"] == "json_invalid"
    assert set(response.json()["detail"][0]) == {"loc", "type", "msg"}
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
    assert response.json()["detail"] == [
        {"loc": ["body", "password"], "type": "value_error", "msg": "Invalid value"}
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
    assert response.json() == {
        "detail": [
            {"loc": ["query", "limit"], "type": "int_parsing", "msg": "Invalid value"}
        ]
    }


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
    assert response.json()["eneo_error_code"] == ErrorCodes.NAME_COLLISION


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
