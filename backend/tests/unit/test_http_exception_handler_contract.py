import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.api_key_router_helpers import raise_api_key_http_error
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError
from eneo.server.main import get_application
from eneo.server.middleware import cors as cors_module


def _build_client_for_exception(detail, *, status_code: int = 503, headers=None):
    app = get_application()

    @app.get("/_test-http-exc")
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Test-only route for HTTP exception handling.",
    )
    async def _test_http_exc():
        raise HTTPException(status_code=status_code, detail=detail, headers=headers)

    return TestClient(app)


def test_http_exception_string_detail_answers_in_the_envelope():
    """The message becomes the envelope's `message`; the string stays in
    `detail` for one release. No numeric category is inferred: both clients
    prefer a category's catalog text over the specific message."""
    client = _build_client_for_exception("Temporary outage")
    response = client.get("/_test-http-exc", headers={"X-Correlation-ID": "req-1"})

    assert response.status_code == 503
    payload = response.json()
    assert payload == {
        "message": "Temporary outage",
        "request_id": "req-1",
        "detail": "Temporary outage",
    }
    assert GeneralError.model_validate(payload).eneo_error_code is None


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
    assert payload["detail"] == {"code": "insufficient_scope", "message": "Denied"}


def test_http_exception_structured_detail_is_unchanged():
    detail = {
        "status": "UNHEALTHY",
        "backend": {"ok": False, "reason": "db_timeout"},
    }
    client = _build_client_for_exception(detail)
    response = client.get("/_test-http-exc")

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"] == detail
    assert payload["message"] == "Something went wrong."
    assert GeneralError.model_validate(payload).details == detail


def test_dict_detail_message_without_code_is_the_envelope_message():
    detail = {"error": "missing_credential", "message": "Add a key.", "hint": "h"}
    client = _build_client_for_exception(detail)
    payload = client.get("/_test-http-exc").json()

    assert payload["message"] == "Add a key."
    assert payload["detail"] == detail


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
    assert payload["detail"] == [
        {
            "loc": ["body", "password"],
            "msg": "String should have at least 8 characters",
            "type": "string_too_short",
        }
    ]
    assert "submitted-secret" not in response.text


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, ErrorCodes.BAD_REQUEST),
        (401, ErrorCodes.AUTHENTICATION_ERROR),
        (403, ErrorCodes.UNAUTHORIZED),
        (404, ErrorCodes.NOT_FOUND),
        (409, ErrorCodes.CONFLICT),
        (429, ErrorCodes.QUOTA_EXCEEDED),
        (503, ErrorCodes.INTERNAL_SERVER_ERROR),
    ],
)
def test_code_message_detail_gets_the_numeric_category(status_code, expected):
    """Routes document these responses as GeneralError, which requires the
    numeric category, while each raiser builds its own detail dict."""
    app = get_application()

    @app.get("/_test-coded-error")
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Test-only route for coded HTTP exceptions.",
    )
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
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Test-only route for explicit error categories.",
    )
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
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Test-only route for API key error handling.",
    )
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
    """The real approval-conflict body: a 409 is the generic conflict, not a
    name collision, which the web client renders as "display name already
    exists"."""
    app = get_application()

    @app.post("/_test-conflict")
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Test-only route for conflict error handling.",
    )
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
    assert payload["eneo_error_code"] == ErrorCodes.CONFLICT.value
    assert payload["code"] == "approval_conflict"
    assert payload["existing_status"] == "approved"


def _contract_app():
    app = get_application()

    @app.get("/_test-status/{status_code}")
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Test-only route for the error envelope contract.",
    )
    async def _test_status(status_code: int):
        raise HTTPException(status_code=status_code, detail=f"Refused {status_code}")

    @app.post("/_test-post-only")
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Test-only route for the 405 error envelope.",
    )
    async def _test_post_only():
        return {}

    @app.get("/_test-unhandled")
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Test-only route for the unhandled error envelope.",
    )
    async def _test_unhandled():
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 413, 429, 503])
def test_every_raised_status_answers_in_the_documented_envelope(status_code):
    response = _contract_app().get(
        f"/_test-status/{status_code}", headers={"X-Request-ID": "req-c"}
    )

    assert response.status_code == status_code
    error = GeneralError.model_validate(response.json())
    assert error.message == f"Refused {status_code}"
    assert error.request_id == "req-c"


def test_unknown_route_answers_in_the_documented_envelope():
    """Starlette raises its own HTTPException for routing misses; the one
    handler is registered on that base class, so it shapes those too."""
    response = _contract_app().get("/_test-no-such-route")

    assert response.status_code == 404
    payload = response.json()
    assert GeneralError.model_validate(payload).message == "Not Found"
    assert payload["detail"] == "Not Found"


def test_wrong_method_answers_in_the_documented_envelope():
    response = _contract_app().get("/_test-post-only")

    assert response.status_code == 405
    assert GeneralError.model_validate(response.json()).message == (
        "Method Not Allowed"
    )
    assert response.headers["allow"] == "POST"


def test_validation_error_keeps_its_list_shape():
    response = _contract_app().get("/_test-status/not-a-number")

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def _origin_checks(monkeypatch, *results):
    """Answer the CORS origin checks in order: a bool, or an exception to raise."""
    answers = iter(results)

    async def check(*_args, **_kwargs):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setitem(cors_module.CORS_OPTIONS, "callback", check)


def test_unhandled_error_carries_cors_trace_and_error_id(monkeypatch):
    # The middleware's check, then the 500 handler's own.
    _origin_checks(monkeypatch, True, True)
    response = _contract_app().get(
        "/_test-unhandled", headers={"Origin": "https://app.example.com"}
    )

    assert response.status_code == 500
    payload = response.json()
    assert len(payload["error_id"]) == 8
    GeneralError.model_validate(payload)
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
    assert response.headers["x-trace-id"]
    expose = response.headers["access-control-expose-headers"].lower()
    assert "x-trace-id" in expose and "x-correlation-id" in expose


def test_unhandled_error_keeps_its_json_body_when_the_origin_check_fails(monkeypatch):
    """The origin check can need the database the 500 came from."""
    _origin_checks(monkeypatch, True, RuntimeError("database unavailable"))
    response = _contract_app().get(
        "/_test-unhandled", headers={"Origin": "https://app.example.com"}
    )

    assert response.status_code == 500
    payload = response.json()
    assert len(payload["error_id"]) == 8
    GeneralError.model_validate(payload)
    assert "access-control-allow-origin" not in response.headers


def test_rate_limit_body_is_readable_flat_and_through_detail():
    """Production Svelte reads `body.detail.code`; web-next reads the flat
    `retry_after_seconds`. Both stay readable."""
    detail = {
        "code": "rate_limit_exceeded",
        "message": "Too many attempts.",
        "retry_after_seconds": 30,
    }
    client = _build_client_for_exception(detail=detail, status_code=429)

    response = client.get("/_test-http-exc")

    assert response.status_code == 429
    payload = response.json()
    GeneralError.model_validate(payload)
    assert payload["code"] == "rate_limit_exceeded"
    assert payload["retry_after_seconds"] == 30
    assert payload["detail"]["code"] == "rate_limit_exceeded"


def test_raised_detail_is_not_mutated_by_the_handler():
    detail = {"code": "insufficient_scope", "message": "Denied"}
    client = _build_client_for_exception(detail)

    client.get("/_test-http-exc", headers={"X-Correlation-ID": "req-3"})

    assert detail == {"code": "insufficient_scope", "message": "Denied"}
