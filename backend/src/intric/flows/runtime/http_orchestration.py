from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Protocol

import httpx
from pydantic import ValidationError

from intric.audit.domain.outcome import Outcome
from intric.flows.domain.flow import FlowPersistedJsonObject
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.http_transport import (
    EffectiveHttpRequest,
    HttpAuthoredConfig,
    HttpMethod,
    compile_http_config,
    decrypt_authored_config,
    is_authored_config,
)
from intric.main.exceptions import BadRequestException, TypedIOValidationException


class RuntimeHttpStep(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def step_id(self) -> Any: ...

    @property
    def input_type(self) -> str: ...

    @property
    def input_source(self) -> str: ...

    @property
    def input_config(self) -> dict[str, Any] | None: ...

    @property
    def output_config(self) -> dict[str, Any] | None: ...

    @property
    def user_description(self) -> str | None: ...


class RuntimeHttpRun(Protocol):
    @property
    def id(self) -> Any: ...

    @property
    def flow_id(self) -> Any: ...

    @property
    def tenant_id(self) -> Any: ...


class ResolveTimeoutFn(Protocol):
    def __call__(
        self,
        timeout_value: Any,
        *,
        step_order: int,
        config_label: str,
    ) -> float: ...


class ReadResponseTextFn(Protocol):
    def __call__(
        self,
        *,
        response: httpx.Response,
        step_order: int,
        code: str,
    ) -> str: ...


SendHttpRequestFn = Callable[..., Awaitable[httpx.Response]]
AuditHttpOutboundFn = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class FlowHttpOrchestrationDeps:
    encryption_service: Any
    variable_resolver: Any
    resolve_timeout_seconds: ResolveTimeoutFn
    read_response_text: ReadResponseTextFn
    send_http_request: SendHttpRequestFn
    audit_http_outbound: AuditHttpOutboundFn


def _compile_authored_http_request(
    *,
    raw_config: FlowPersistedJsonObject,
    direction: str,
    method: HttpMethod,
    context: FlowPersistedJsonObject,
    step_order: int,
    config_label: str,
    deps: FlowHttpOrchestrationDeps,
) -> tuple[EffectiveHttpRequest, str | None]:
    if not is_authored_config(raw_config):
        raise TypedIOValidationException(
            _authored_http_config_required_message(
                step_order=step_order,
                config_label=config_label,
            ),
            code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        )
    try:
        authored = HttpAuthoredConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise TypedIOValidationException(
            f"Step {step_order}: {config_label} is not a valid authored HTTP config.",
            code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        ) from exc

    decrypted = decrypt_authored_config(authored, deps.encryption_service)
    effective_request = compile_http_config(
        decrypted,
        direction=direction,
        method=method,
        variables=context,
        interpolate=deps.variable_resolver.interpolate,
    )
    timeout_seconds = deps.resolve_timeout_seconds(
        decrypted.timeout_seconds,
        step_order=step_order,
        config_label=config_label,
    )
    return (
        replace(
            effective_request,
            url=effective_request.url.strip(),
            timeout=timeout_seconds,
        ),
        decrypted.response_format,
    )


def _authored_http_config_required_message(
    *,
    step_order: int,
    config_label: str,
) -> str:
    return (
        f"Step {step_order}: {config_label} must use authored HTTP config with an auth field; "
        "legacy flat HTTP config is no longer supported."
    )


async def resolve_http_input_source_text(
    *,
    step: RuntimeHttpStep,
    run: RuntimeHttpRun,
    context: dict[str, Any],
    deps: FlowHttpOrchestrationDeps,
) -> tuple[str, dict[str, Any] | list[Any] | None]:
    if not isinstance(step.input_config, dict):
        raise TypedIOValidationException(
            f"Step {step.step_order}: HTTP input source requires input_config object.",
            code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        )

    method: HttpMethod = "GET" if step.input_source == "http_get" else "POST"
    effective_request, response_format = _compile_authored_http_request(
        raw_config=step.input_config,
        direction="input",
        method=method,
        context=context,
        step_order=step.step_order,
        config_label="input_config",
        deps=deps,
    )
    url = effective_request.url
    if not url:
        raise TypedIOValidationException(
            f"Step {step.step_order}: input_config.url is required for HTTP input.",
            code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        )
    timeout_seconds = effective_request.timeout
    headers = dict(effective_request.headers)
    body_bytes = effective_request.body
    json_body = effective_request.json_body

    start_time = time.monotonic()
    try:
        response = await deps.send_http_request(
            method=method,
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            body_bytes=body_bytes,
            json_body=json_body,
        )
    except TypedIOValidationException as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method=method,
            call_type="http_input",
            outcome=Outcome.FAILURE,
            error_message=str(exc),
            duration_ms=duration_ms,
        )
        raise
    except httpx.TimeoutException as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        err_msg = f"Step {step.step_order}: HTTP {method} input timed out after {timeout_seconds:g}s."
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method=method,
            call_type="http_input",
            outcome=Outcome.FAILURE,
            error_message=err_msg,
            duration_ms=duration_ms,
        )
        raise TypedIOValidationException(
            err_msg,
            code=FlowApiErrorCode.TYPED_IO_HTTP_TIMEOUT.value,
        ) from exc
    except httpx.HTTPError as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        err_msg = f"Step {step.step_order}: HTTP {method} input request failed: {exc}"
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method=method,
            call_type="http_input",
            outcome=Outcome.FAILURE,
            error_message=err_msg,
            duration_ms=duration_ms,
        )
        raise TypedIOValidationException(
            err_msg,
            code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR.value,
        ) from exc

    duration_ms = (time.monotonic() - start_time) * 1000
    if response.status_code >= 400:
        err_msg = f"Step {step.step_order}: HTTP {method} input returned status {response.status_code}."
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method=method,
            call_type="http_input",
            outcome=Outcome.FAILURE,
            error_message=err_msg,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        raise TypedIOValidationException(
            err_msg,
            code=FlowApiErrorCode.TYPED_IO_HTTP_NON_SUCCESS.value,
        )

    response_text = deps.read_response_text(
        response=response,
        step_order=step.step_order,
        code=FlowApiErrorCode.TYPED_IO_HTTP_RESPONSE_TOO_LARGE.value,
    )

    expects_json = step.input_type == "json" or str(response_format or "text") == "json"
    if expects_json:
        try:
            parsed = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            err_msg = f"Step {step.step_order}: HTTP {method} input returned malformed JSON response."
            await deps.audit_http_outbound(
                run=run,
                step=step,
                url=url,
                method=method,
                call_type="http_input",
                outcome=Outcome.FAILURE,
                error_message=err_msg,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            raise TypedIOValidationException(
                err_msg,
                code=FlowApiErrorCode.TYPED_IO_HTTP_MALFORMED_RESPONSE.value,
            ) from exc
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method=method,
            call_type="http_input",
            outcome=Outcome.SUCCESS,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return json.dumps(parsed, ensure_ascii=False), parsed

    await deps.audit_http_outbound(
        run=run,
        step=step,
        url=url,
        method=method,
        call_type="http_input",
        outcome=Outcome.SUCCESS,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response_text, None


async def deliver_webhook(
    *,
    step: RuntimeHttpStep,
    text_payload: str,
    run: RuntimeHttpRun,
    context: dict[str, Any],
    deps: FlowHttpOrchestrationDeps,
    idempotency_key: str,
) -> None:
    if step.output_config is None:
        return
    if not is_authored_config(step.output_config):
        raise BadRequestException(
            _authored_http_config_required_message(
                step_order=step.step_order,
                config_label="output_config",
            )
        )
    try:
        effective_request, _ = _compile_authored_http_request(
            raw_config=step.output_config,
            direction="output",
            method="POST",
            context=context,
            step_order=step.step_order,
            config_label="output_config",
            deps=deps,
        )
    except TypedIOValidationException as exc:
        raise BadRequestException(str(exc)) from exc
    url = effective_request.url
    if not url:
        raise BadRequestException("Webhook output mode requires output_config.url.")
    timeout_seconds = effective_request.timeout
    headers = dict(effective_request.headers)
    body_bytes = effective_request.body
    json_body = effective_request.json_body
    if body_bytes is None and json_body is None:
        body_bytes = text_payload.encode("utf-8")
    headers["Idempotency-Key"] = hashlib.sha256(
        idempotency_key.encode("utf-8")
    ).hexdigest()

    start_time = time.monotonic()
    try:
        response = await deps.send_http_request(
            method="POST",
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            body_bytes=body_bytes,
            json_body=json_body,
            read_response_body=False,
        )
    except TypedIOValidationException as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method="POST",
            call_type="webhook_delivery",
            outcome=Outcome.FAILURE,
            error_message=str(exc),
            duration_ms=duration_ms,
        )
        raise BadRequestException(str(exc)) from exc
    except httpx.TimeoutException as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        err_msg = f"Webhook delivery timed out after {timeout_seconds:g}s."
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method="POST",
            call_type="webhook_delivery",
            outcome=Outcome.FAILURE,
            error_message=err_msg,
            duration_ms=duration_ms,
        )
        raise BadRequestException(err_msg) from exc
    except httpx.HTTPError as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        err_msg = f"Webhook delivery failed: {exc}"
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method="POST",
            call_type="webhook_delivery",
            outcome=Outcome.FAILURE,
            error_message=err_msg,
            duration_ms=duration_ms,
        )
        raise BadRequestException(err_msg) from exc

    duration_ms = (time.monotonic() - start_time) * 1000
    if response.status_code >= 400:
        err_msg = f"Webhook delivery returned status {response.status_code}."
        await deps.audit_http_outbound(
            run=run,
            step=step,
            url=url,
            method="POST",
            call_type="webhook_delivery",
            outcome=Outcome.FAILURE,
            error_message=err_msg,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        raise BadRequestException(err_msg)
    await deps.audit_http_outbound(
        run=run,
        step=step,
        url=url,
        method="POST",
        call_type="webhook_delivery",
        outcome=Outcome.SUCCESS,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
