from fastapi import FastAPI
from fastapi.testclient import TestClient

from eneo.object_content.content import (
    ObjectContentIdempotencyConflictError,
    ObjectContentIntegrityError,
    ObjectContentUnavailableError,
)
from eneo.server.exception_handlers import add_exception_handlers


def _client_for(error: Exception) -> TestClient:
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/failure")
    async def fail() -> None:
        raise error

    return TestClient(app, raise_server_exceptions=False)


def test_store_unavailable_has_stable_typed_503_contract() -> None:
    response = _client_for(
        ObjectContentUnavailableError(
            "Durable object content is temporarily unavailable"
        )
    ).get("/failure")

    assert response.status_code == 503
    assert response.json() == {
        "message": "Durable object content is temporarily unavailable",
        "eneo_error_code": 9038,
        "code": "object_content_unavailable",
    }


def test_integrity_failure_has_stable_typed_503_contract() -> None:
    response = _client_for(
        ObjectContentIntegrityError("Durable object verification failed")
    ).get("/failure")

    assert response.status_code == 503
    assert response.json()["code"] == "object_content_integrity_failure"


def test_idempotency_conflict_is_not_reported_as_server_failure() -> None:
    response = _client_for(
        ObjectContentIdempotencyConflictError(
            "The idempotency key is bound to another request"
        )
    ).get("/failure")

    assert response.status_code == 409
    assert response.json()["code"] == "object_content_idempotency_conflict"
