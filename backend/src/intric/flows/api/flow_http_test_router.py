from __future__ import annotations

import logging
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api import flow_http_test_models
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_definition_access import require_flow_edit_access
from intric.flows.http_transport import (
    HttpAuthoredConfig,
    HttpTemplateInterpolationError,
    is_authored_config,
)
from intric.flows.http_transport.test_action import execute_http_test
from intric.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from intric.flows.variable_resolver import FlowVariableResolver
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException, ErrorCodes
from intric.server.dependencies.container import get_container

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/{id}/http-test",
    response_model=flow_http_test_models.HttpTestResponse,
    status_code=status.HTTP_200_OK,
    operation_id="test_flow_http",
    summary="Test HTTP Connection",
    description=(
        "Send a test HTTP request using the submitted authored config snapshot and "
        "return a typed preview of the attempted request and response. This endpoint "
        "does not persist the config or publish the flow; it is for authoring UIs that "
        "need to validate URL, auth, timeout, headers, body mode, and SSRF guard behavior "
        "before saving an HTTP input or output step. `test_variables` is the raw "
        "template context used for URL, header, auth, and body interpolation; callers "
        "can send flat keys such as `name` or runtime-shaped keys such as `flow_input` "
        "and `step_1`."
    ),
    responses={
        200: {
            "description": (
                "HTTP test result. `success=false` is still returned with 200 when "
                "the submitted config is syntactically valid but the target request "
                "fails, times out, returns an error status, or references a stored "
                "secret that cannot be resolved."
            ),
        },
        403: error_response(
            description="Caller lacks permission to edit this flow.",
            message="Insufficient permissions.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "space_membership"},
        ),
    },
)
async def test_flow_http(
    id: Annotated[UUID, Path(description="Flow ID")],
    request: Request,
    body: flow_http_test_models.HttpTestRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    import httpx as _httpx

    await require_flow_edit_access(request, container, flow_id=id)
    settings = get_settings()

    config = body.config
    flow_service = container.flow_service()
    flow = await flow_service.get_flow(id)
    stored_config = find_stored_http_config(flow, body.direction)
    encryption_service = (
        container.encryption_service()
        if hasattr(container, "encryption_service")
        else None
    )
    variable_resolver = FlowVariableResolver()
    http_runtime = FlowHttpRuntimeHelper(
        variable_resolver=variable_resolver,
        request_timeout_seconds=float(settings.flow_http_request_timeout_seconds),
        max_timeout_seconds=float(settings.flow_http_max_timeout_seconds),
        allow_private_networks=bool(settings.flow_http_allow_private_networks),
    )

    def _interpolate_http_test_template(template: str, context: dict[str, Any]) -> str:
        try:
            return variable_resolver.interpolate(template, context)
        except BadRequestException as exc:
            raise HttpTemplateInterpolationError(str(exc)) from exc

    async def _send(
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        body_bytes: bytes | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        **_kwargs: object,
    ) -> _httpx.Response:
        preflight_resolved_ips = await http_runtime.assert_url_allowed(url)
        async with _httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body_bytes,
                json=json_body,
                timeout=timeout_seconds,
            )
        http_runtime.assert_connected_peer_allowed(
            response=response,
            preflight_resolved_ips=preflight_resolved_ips,
        )
        return response

    result = await execute_http_test(
        config=config,
        direction=body.direction,
        method=body.method,
        test_variables=body.test_variables,
        stored_config=stored_config,
        encryption_service=encryption_service,
        interpolate=_interpolate_http_test_template,
        send_http_request=_send,
        max_timeout=float(settings.flow_http_max_timeout_seconds),
    )

    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UPDATED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Tested HTTP {body.method} connection for flow",
        metadata=AuditMetadata.standard(
            actor=user,
            target=flow,
            extra={"test_direction": body.direction, "test_success": result.success},
        ),
    )

    return flow_http_test_models.HttpTestResponse(
        success=result.success,
        status_code=result.status_code,
        duration_ms=result.duration_ms,
        response_preview=result.response_preview,
        request_preview=result.request_preview,
        error_code=result.error_code,
        error_message=result.error_message,
    )


def find_stored_http_config(flow: Any, direction: str) -> HttpAuthoredConfig | None:
    for step in flow.steps:
        raw_config = step.output_config if direction == "output" else step.input_config
        if isinstance(raw_config, dict):
            config = cast(dict[str, Any], raw_config)
        else:
            config = None
        if config is not None and is_authored_config(config):
            try:
                return HttpAuthoredConfig.model_validate(config)
            except Exception:
                logger.warning(
                    "Failed to parse stored HTTP config for flow step during http-test secret merge",
                    extra={
                        "flow_id": (
                            str(getattr(flow, "id", ""))
                            if getattr(flow, "id", None) is not None
                            else None
                        ),
                        "step_id": (
                            str(getattr(step, "id", ""))
                            if getattr(step, "id", None) is not None
                            else None
                        ),
                        "direction": direction,
                    },
                )
    return None


__all__ = ["router"]
