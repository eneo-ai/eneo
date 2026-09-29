import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.api_key_router_helpers import raise_api_key_http_error
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError
from eneo.server.main import get_application


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


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, ErrorCodes.BAD_REQUEST),
        (401, ErrorCodes.AUTHENTICATION_ERROR),
        (403, ErrorCodes.UNAUTHORIZED),
        (404, ErrorCodes.NOT_FOUND),
        (429, ErrorCodes.QUOTA_EXCEEDED),
        (503, ErrorCodes.INTERNAL_SERVER_ERROR),
    ],
)
def test_code_message_detail_gets_the_numeric_category(status_code, expected):
    """Routes document these responses as GeneralError, which requires the
    numeric category, while each raiser builds its own detail dict."""
    app = get_application()

    @app.get("/_test-coded-error")
    async def _test_coded_error():
        raise HTTPException(
            status_code=status_code,
            detail={"code": "resource_not_found", "message": "API key not found."},
        )

    response = TestClient(app).get("/_test-coded-error")

    assert response.status_code == status_code
    payload = response.json()
    assert payload["eneo_error_code"] == expected.value
    assert GeneralError.model_validate(payload).code == "resource_not_found"


def test_raiser_supplied_category_is_kept():
    app = get_application()

    @app.get("/_test-owned-category")
    async def _test_owned_category():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "quota_exceeded",
                "message": "Out of quota.",
                "eneo_error_code": ErrorCodes.QUOTA_EXCEEDED.value,
            },
        )

    payload = TestClient(app).get("/_test-owned-category").json()

    assert payload["eneo_error_code"] == ErrorCodes.QUOTA_EXCEEDED.value


def test_api_key_refusal_validates_as_the_documented_error():
    """The converter every API-key path routes through, read through the
    handler: the bypassing routes are covered by the case above."""
    app = get_application()

    @app.get("/_test-api-key-error")
    async def _test_api_key_error():
        raise_api_key_http_error(
            ApiKeyValidationError(
                status_code=401,
                code="invalid_api_key",
                message="API key is invalid.",
            )
        )

    response = TestClient(app).get("/_test-api-key-error")

    assert response.status_code == 401
    error = GeneralError.model_validate(response.json())
    assert error.code == "invalid_api_key"
    assert error.eneo_error_code == ErrorCodes.AUTHENTICATION_ERROR
    assert error.context == {"auth_layer": "identity"}


def test_conflict_does_not_borrow_a_domain_category():
    """The real approval-conflict body: a 409 is not a name collision, and the
    web client renders 9017 as "display name already exists"."""
    app = get_application()

    @app.post("/_test-conflict")
    async def _test_conflict():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "approval_conflict",
                "message": "This approval request was already processed with a different decision set.",
                "existing_status": "approved",
            },
        )

    payload = TestClient(app).post("/_test-conflict").json()

    assert payload["eneo_error_code"] != ErrorCodes.NAME_COLLISION.value
    assert payload["eneo_error_code"] == ErrorCodes.BAD_REQUEST.value
    assert payload["code"] == "approval_conflict"
    assert payload["existing_status"] == "approved"
