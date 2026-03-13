from fastapi import FastAPI
from fastapi.testclient import TestClient

from intric.main.exceptions import (
    BadRequestException,
    ErrorCodes,
    FileTooLargeException,
)
from intric.server.exception_handlers import add_exception_handlers


def test_file_too_large_exception_includes_structured_details():
    exception = FileTooLargeException(
        file_size=12_582_912,
        max_size=10_485_760,
        setting_name="UPLOAD_MAX_FILE_SIZE",
    )

    # setting_name and docs_hint should be in the message (for logs) but not in details
    assert "UPLOAD_MAX_FILE_SIZE" in str(exception)
    assert "README" in str(exception)
    assert exception.details["file_size_bytes"] == 12_582_912
    assert exception.details["max_size_bytes"] == 10_485_760
    assert "setting_name" not in exception.details
    assert "docs_hint" not in exception.details


def test_exception_handler_returns_file_size_details_for_413():
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/raise")
    async def raise_exception():
        raise FileTooLargeException(
            file_size=2_048,
            max_size=1_024,
            setting_name="UPLOAD_MAX_FILE_SIZE",
        )

    client = TestClient(app)
    response = client.get("/raise")

    assert response.status_code == 413
    body = response.json()
    assert body["intric_error_code"] == ErrorCodes.FILE_TOO_LARGE
    assert body["details"]["file_size_bytes"] == 2_048
    assert body["details"]["max_size_bytes"] == 1_024
    # Internal config (setting_name) should not leak to clients
    assert "setting_name" not in body["details"]


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
    assert body["intric_error_code"] == ErrorCodes.BAD_REQUEST
    assert "details" not in body
