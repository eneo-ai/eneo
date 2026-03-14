from fastapi import HTTPException
from fastapi.testclient import TestClient

from intric.server.main import get_application


def _build_client_for_exception(detail):
    app = get_application()

    @app.get("/_test-http-exc")
    async def _test_http_exc():
        raise HTTPException(status_code=503, detail=detail)

    return TestClient(app)


def test_http_exception_string_detail_preserves_legacy_shape():
    client = _build_client_for_exception("Temporary outage")
    response = client.get("/_test-http-exc", headers={"X-Correlation-ID": "req-1"})

    assert response.status_code == 503
    payload = response.json()
    assert payload == {"detail": "Temporary outage"}


def test_http_exception_code_message_preserved_and_request_id_added():
    client = _build_client_for_exception({"code": "insufficient_scope", "message": "Denied"})
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
