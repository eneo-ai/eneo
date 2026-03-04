from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

import httpx

from intric.audit.domain.outcome import Outcome
from intric.flows.step_config_secrets import decrypt_step_headers_for_runtime
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


class BuildHeadersFn(Protocol):
    def __call__(
        self,
        headers_raw: Any,
        *,
        context: dict[str, Any],
        step_order: int,
        config_label: str,
    ) -> dict[str, str]: ...


class ResolveRequestBodyFn(Protocol):
    def __call__(
        self,
        *,
        method: str,
        config: dict[str, Any],
        context: dict[str, Any],
        step_order: int,
        config_label: str,
    ) -> tuple[bytes | None, dict[str, Any] | list[Any] | None]: ...


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
    build_headers: BuildHeadersFn
    resolve_request_body: ResolveRequestBodyFn
    read_response_text: ReadResponseTextFn
    send_http_request: SendHttpRequestFn
    audit_http_outbound: AuditHttpOutboundFn


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
            code="typed_io_http_invalid_config",
        )
    resolved_config = decrypt_step_headers_for_runtime(
        config=step.input_config,
        encryption_service=deps.encryption_service,
    ) or {}
    if not isinstance(resolved_config, dict):
        raise TypedIOValidationException(
            f"Step {step.step_order}: HTTP input config must be an object.",
            code="typed_io_http_invalid_config",
        )

    url_raw = resolved_config.get("url")
    if not isinstance(url_raw, str) or not url_raw.strip():
        raise TypedIOValidationException(
            f"Step {step.step_order}: input_config.url is required for HTTP input.",
            code="typed_io_http_invalid_config",
        )
    url = deps.variable_resolver.interpolate(url_raw, context).strip()
    timeout_seconds = deps.resolve_timeout_seconds(
        resolved_config.get("timeout_seconds"),
        step_order=step.step_order,
        config_label="input_config",
    )
    headers = deps.build_headers(
        resolved_config.get("headers"),
        context=context,
        step_order=step.step_order,
        config_label="input_config",
    )

    method = "GET" if step.input_source == "http_get" else "POST"
    body_bytes, json_body = deps.resolve_request_body(
        method=method,
        config=resolved_config,
        context=context,
        step_order=step.step_order,
        config_label="input_config",
    )

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
            code="typed_io_http_timeout",
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
            code="typed_io_http_connection_error",
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
            code="typed_io_http_non_success",
        )

    response_text = deps.read_response_text(
        response=response,
        step_order=step.step_order,
        code="typed_io_http_response_too_large",
    )

    expects_json = (
        step.input_type == "json"
        or str(resolved_config.get("response_format", "text")) == "json"
    )
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
                code="typed_io_http_malformed_response",
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
) -> None:
    if not step.output_config:
        return
    if not isinstance(step.output_config, dict):
        raise BadRequestException("Webhook output_config must be an object.")
    resolved_config = decrypt_step_headers_for_runtime(
        config=step.output_config,
        encryption_service=deps.encryption_service,
    ) or {}
    if not isinstance(resolved_config, dict):
        raise BadRequestException("Webhook output_config must be an object.")
    url_raw = resolved_config.get("url")
    if not isinstance(url_raw, str) or not url_raw.strip():
        raise BadRequestException("Webhook output mode requires output_config.url.")

    url = deps.variable_resolver.interpolate(url_raw, context).strip()
    timeout_seconds = deps.resolve_timeout_seconds(
        resolved_config.get("timeout_seconds"),
        step_order=step.step_order,
        config_label="output_config",
    )
    headers = deps.build_headers(
        resolved_config.get("headers"),
        context=context,
        step_order=step.step_order,
        config_label="output_config",
    )
    body_bytes, json_body = deps.resolve_request_body(
        method="POST",
        config=resolved_config,
        context=context,
        step_order=step.step_order,
        config_label="output_config",
    )
    if body_bytes is None and json_body is None:
        body_bytes = text_payload.encode("utf-8")
    idempotency = hashlib.sha256(f"{run.id}:{step.step_id}".encode("utf-8")).hexdigest()
    headers["Idempotency-Key"] = idempotency

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
