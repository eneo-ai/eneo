import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
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
    assert "platform administrator" in str(exception)
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
