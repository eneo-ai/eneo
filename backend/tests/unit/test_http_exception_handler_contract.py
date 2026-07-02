from fastapi import HTTPException
from fastapi.testclient import TestClient

from eneo.main.exceptions import ErrorCodes
from eneo.server.main import get_application


def _build_client_for_exception(detail, *, status_code: int = 503, headers=None):
    app = get_application()

    @app.get("/_test-http-exc")
    async def _test_http_exc():
        raise HTTPException(status_code=status_code, detail=detail, headers=headers)

    return TestClient(app)


def test_http_exception_string_detail_preserves_legacy_shape():
    client = _build_client_for_exception("Temporary outage")
    response = client.get("/_test-http-exc", headers={"X-Correlation-ID": "req-1"})

    assert response.status_code == 503
    payload = response.json()
    assert payload == {"detail": "Temporary outage"}


def test_http_exception_code_message_preserved_and_request_id_added():
    client = _build_client_for_exception(
        {"code": "insufficient_scope", "message": "Denied"}
    )
    response = client.get("/_test-http-exc", headers={"X-Correlation-ID": "req-2"})

    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "insufficient_scope"
    assert payload["message"] == "Denied"
    assert payload["request_id"] == "req-2"


def test_http_exception_structured_detail_is_unchanged():
    detail = {
        "status": "UNHEALTHY",
        "backend": {"ok": False, "reason": "db_timeout"},
    }
    client = _build_client_for_exception(detail)
    response = client.get("/_test-http-exc")

    assert response.status_code == 503
    payload = response.json()
    assert payload == {"detail": detail}


def test_http_exception_422_uses_validation_general_error_and_preserves_headers():
    client = _build_client_for_exception(
        [
            {
                "loc": ["body", "password"],
                "msg": "String should have at least 8 characters",
                "type": "string_too_short",
                "input": "submitted-secret",
            }
        ],
        status_code=422,
        headers={"X-Correlation-ID": "exception-correlation-id"},
    )
    response = client.get("/_test-http-exc", headers={"X-Request-ID": "req-422"})

    assert response.status_code == 422
    assert response.headers["x-correlation-id"] == "exception-correlation-id"
    payload = response.json()
    assert payload["message"] == "Request validation failed."
    assert payload["eneo_error_code"] == ErrorCodes.VALIDATION_ERROR
    assert payload["code"] == "request_validation_error"
    assert payload["request_id"] == "req-422"
    assert payload["details"] == {
        "errors": [
            {
                "location": ["body", "password"],
                "message": "String should have at least 8 characters",
                "type": "string_too_short",
            }
        ]
    }
    assert "detail" not in payload
    assert "submitted-secret" not in response.text
