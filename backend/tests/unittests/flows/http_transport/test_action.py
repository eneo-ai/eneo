from __future__ import annotations

from typing import Any

import httpx
import pytest

from eneo.flows.http_transport.authored_config import (
    SECRET_SENTINEL,
    CustomHeader,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBody,
    HttpBodyMode,
)
from eneo.flows.http_transport.errors import HttpTransportError
from eneo.flows.http_transport.test_action import execute_http_test
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import BadRequestException


def _config(
    *,
    url: str = "https://example.org/api",
    auth: HttpAuthBearer | HttpAuthNone | None = None,
    body: HttpBody | None = None,
    custom_headers: list[CustomHeader] | None = None,
) -> HttpAuthoredConfig:
    return HttpAuthoredConfig(
        url=url,
        auth=auth or HttpAuthNone(),
        body=body or HttpBody(mode=HttpBodyMode.AUTO),
        custom_headers=custom_headers or [],
        timeout_seconds=30,
    )


def _interpolate(template: str, context: dict[str, Any]) -> str:
    return FlowVariableResolver().interpolate(template, context)


def _transport_interpolate(template: str, context: dict[str, Any]) -> str:
    from eneo.flows.http_transport.errors import HttpTemplateInterpolationError

    try:
        return _interpolate(template, context)
    except BadRequestException as exc:
        raise HttpTemplateInterpolationError(str(exc)) from exc


@pytest.mark.asyncio
async def test_execute_http_test_interpolates_raw_context_before_send() -> None:
    sent: dict[str, Any] = {}

    async def _send_http_request(**kwargs: Any) -> httpx.Response:
        sent.update(kwargs)
        request = httpx.Request(method=kwargs["method"], url=kwargs["url"])
        return httpx.Response(status_code=200, text="ok", request=request)

    result = await execute_http_test(
        config=_config(
            url="{{base_url}}/events/{{name}}",
            auth=HttpAuthBearer(token="{{token}}"),
            custom_headers=[
                CustomHeader(name="X-Case", value="{{flow_input.case_id}}"),
            ],
            body=HttpBody(
                mode=HttpBodyMode.JSON_TEMPLATE,
                template='{"message":"{{text}}"}',
            ),
        ),
        direction="output",
        method="POST",
        test_variables={
            "base_url": "https://example.org",
            "name": "alex",
            "token": "sekret-token-123",
            "flow_input": {"case_id": "CASE-1"},
            "text": "hello",
        },
        interpolate=_interpolate,
        send_http_request=_send_http_request,
    )

    assert result.success is True
    assert sent["url"] == "https://example.org/events/alex"
    assert sent["headers"]["Authorization"] == "Bearer sekret-token-123"
    assert sent["headers"]["X-Case"] == "CASE-1"
    assert sent["json_body"] == {"message": "hello"}
    assert result.request_preview is not None
    assert result.request_preview.model_dump() == {
        "method": "POST",
        "url": "https://example.org/events/alex",
        "headers": {"Authorization": "Bearer sek...", "X-Case": "CASE-1"},
        "body_preview": '{"message": "hello"}',
    }


@pytest.mark.asyncio
async def test_execute_http_test_returns_typed_variable_failure() -> None:
    async def _send_http_request(**_kwargs: Any) -> httpx.Response:
        raise AssertionError("request should not be sent when interpolation fails")

    result = await execute_http_test(
        config=_config(url="https://example.org/{{missing}}"),
        direction="output",
        method="POST",
        test_variables={},
        interpolate=_transport_interpolate,
        send_http_request=_send_http_request,
    )

    assert result.success is False
    assert result.error_code == HttpTransportError.VARIABLE_RESOLUTION_FAILED
    assert "Unknown variable reference" in (result.error_message or "")
    assert result.request_preview is None


@pytest.mark.asyncio
async def test_execute_http_test_rejects_unresolved_stored_secret() -> None:
    async def _send_http_request(**_kwargs: Any) -> httpx.Response:
        raise AssertionError("request should not be sent without the stored secret")

    result = await execute_http_test(
        config=_config(auth=HttpAuthBearer(token=SECRET_SENTINEL)),
        direction="output",
        method="POST",
        test_variables={},
        interpolate=_transport_interpolate,
        send_http_request=_send_http_request,
    )

    assert result.success is False
    assert result.error_code == HttpTransportError.UNRESOLVED_STORED_SECRET
    assert result.request_preview is None


@pytest.mark.asyncio
async def test_execute_http_test_reports_unresolved_secret_before_url_errors() -> None:
    async def _send_http_request(**_kwargs: Any) -> httpx.Response:
        raise AssertionError("request should not be sent without the stored secret")

    result = await execute_http_test(
        config=_config(url="", auth=HttpAuthBearer(token=SECRET_SENTINEL)),
        direction="output",
        method="POST",
        test_variables={},
        interpolate=_transport_interpolate,
        send_http_request=_send_http_request,
    )

    assert result.success is False
    assert result.error_code == HttpTransportError.UNRESOLVED_STORED_SECRET


@pytest.mark.asyncio
async def test_execute_http_test_validates_effective_url_after_interpolation() -> None:
    async def _send_http_request(**_kwargs: Any) -> httpx.Response:
        raise AssertionError("request should not be sent when effective URL is invalid")

    result = await execute_http_test(
        config=_config(url="{{base_url}}/events"),
        direction="output",
        method="POST",
        test_variables={"base_url": "not-a-url"},
        interpolate=_interpolate,
        send_http_request=_send_http_request,
    )

    assert result.success is False
    assert result.error_code == HttpTransportError.INVALID_URL
    assert result.request_preview is not None
    assert result.request_preview.model_dump() == {
        "method": "POST",
        "url": "not-a-url/events",
        "headers": {},
        "body_preview": None,
    }
