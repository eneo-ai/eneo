from fastapi import FastAPI
from fastapi.testclient import TestClient

from intric.main.exceptions import NotFoundException, UnauthorizedException
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
