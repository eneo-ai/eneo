from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.http_transport.effective_url import (
    InvalidHttpUrl,
    parse_effective_http_url,
)
from eneo.flows.runtime.egress.http import ClientFactory, build_http_client
from eneo.flows.runtime.egress.policy import (
    DestinationRefused,
    DestinationUnresolvable,
    FlowDestinationPolicy,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import TypedIOValidationException

if TYPE_CHECKING:
    from eneo.flows.variable_resolver import FlowVariableResolver


class FlowHttpRuntimeHelper:
    """The Flow HTTP transport owner: URL reading, the destination policy (via
    the egress client), streamed size caps, and request sending for every Flow
    HTTP surface (input fetch, webhook delivery, and the authoring test
    endpoint)."""

    def __init__(
        self,
        *,
        variable_resolver: "FlowVariableResolver",
        request_timeout_seconds: float,
        max_timeout_seconds: float,
        allow_private_networks: bool,
        client_factory: ClientFactory = build_http_client,
    ) -> None:
        self.variable_resolver = variable_resolver
        self.request_timeout_seconds = request_timeout_seconds
        self.max_timeout_seconds = max_timeout_seconds
        self.allow_private_networks = allow_private_networks
        self.destination_policy = FlowDestinationPolicy(
            allow_private_networks=allow_private_networks
        )
        self._client_factory = client_factory

    def resolve_timeout_seconds(
        self,
        timeout_value: Any,
        *,
        step_order: int,
        config_label: str,
    ) -> float:
        if timeout_value is None:
            return self.request_timeout_seconds
        if not isinstance(timeout_value, (int, float)):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds must be a number.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
            )
        timeout_seconds = float(timeout_value)
        if timeout_seconds <= 0:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds must be greater than zero.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
            )
        if timeout_seconds > self.max_timeout_seconds:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds cannot exceed {self.max_timeout_seconds:g}.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
            )
        return timeout_seconds

    @staticmethod
    def read_response_text(
        *,
        response: httpx.Response,
        step_order: int,
        code: str,
    ) -> str:
        response_bytes = response.content
        if len(response_bytes) > get_settings().flow_max_inline_text_bytes:
            raise TypedIOValidationException(
                f"Step {step_order}: HTTP response exceeded max inline text bytes.",
                code=code,
            )
        return response.text

    async def send_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        body_bytes: bytes | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        read_response_body: bool = True,
    ) -> httpx.Response:
        try:
            target = parse_effective_http_url(url)
        except InvalidHttpUrl as exc:
            raise TypedIOValidationException(
                str(exc),
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_URL.value,
            ) from exc
        async with self._client_factory(
            policy=self.destination_policy, timeout_seconds=timeout_seconds
        ) as client:
            # The size cap must bound raw response-body bytes: a compressed
            # body can expand by orders of magnitude in one decode call, so
            # this transport requests identity encoding (replacing any
            # case-variant authored value), refuses compressed replies, and
            # counts raw bytes below.
            request_headers = httpx.Headers(headers)
            request_headers["Accept-Encoding"] = "identity"
            request = client.build_request(
                method,
                target.url,
                headers=request_headers,
                content=body_bytes,
                json=json_body,
            )
            try:
                response = await client.send(request, stream=True)
            except DestinationRefused as exc:
                raise TypedIOValidationException(
                    "HTTP URL blocked by SSRF policy.",
                    code=FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED.value,
                ) from exc
            except DestinationUnresolvable as exc:
                raise TypedIOValidationException(
                    f"Unable to resolve HTTP host '{exc.host}'.",
                    code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR.value,
                ) from exc

            if not read_response_body:
                detached = httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    request=request,
                )
                await response.aclose()
                return detached

            content_encoding = (
                response.headers.get("content-encoding", "identity").strip().lower()
            )
            if content_encoding not in ("", "identity"):
                await response.aclose()
                raise TypedIOValidationException(
                    "HTTP response used a compressed content encoding; this "
                    "transport requires identity encoding to bound memory.",
                    code=FlowApiErrorCode.TYPED_IO_HTTP_RESPONSE_TOO_LARGE.value,
                )

            max_bytes = get_settings().flow_max_inline_text_bytes
            response_bytes = bytearray()
            async for chunk in response.aiter_raw():
                if len(response_bytes) + len(chunk) > max_bytes:
                    await response.aclose()
                    raise TypedIOValidationException(
                        "HTTP response exceeded max inline text bytes.",
                        code=FlowApiErrorCode.TYPED_IO_HTTP_RESPONSE_TOO_LARGE.value,
                    )
                response_bytes.extend(chunk)

            detached = httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=bytes(response_bytes),
                request=request,
            )
            await response.aclose()
            return detached
