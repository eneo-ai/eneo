from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.flow_access_policy import (
    FlowApiAction,
    flow_action_access_reason,
    require_flow_action,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import get_container

router = APIRouter()


class FlowExecutionLimitsPublic(BaseModel):
    """The organisation's step timeout limits, as a run applies them."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "default_step_timeout_seconds": 900,
                "max_step_timeout_seconds": 1800,
            }
        },
    )

    default_step_timeout_seconds: int = Field(
        ge=1,
        description=(
            "Seconds a step may run when its `timeout_seconds` is empty: the "
            "organisation's default, otherwise the deployment ceiling."
        ),
    )
    max_step_timeout_seconds: int = Field(
        ge=1,
        description=(
            "The largest `timeout_seconds` a step may set; a save or run with a "
            "larger one is refused with `flow_step_timeout_exceeds_tenant_max`."
        ),
    )


# A literal one-segment path: its router is included before the `/{id}/` routes.
@router.get(
    "/execution-limits/",
    response_model=FlowExecutionLimitsPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_execution_limits",
    summary="Get Flow Execution Limits",
    description=(
        "Return the step timeout limits of the caller's organisation, so an "
        "editor can show them at a step's `timeout_seconds`: the default a step "
        "without one runs with and the maximum a step may set. They are the "
        "values a run resolves each step's timeout with, from the flow runtime "
        "policy administrators edit at `/settings/flow-runtime-policy`. It needs "
        "the permission to manage flows; service keys are refused."
    ),
    responses={
        200: {"description": "The organisation's effective step timeout limits."},
        403: error_response(
            description=(
                "The caller may not manage flows "
                "(`insufficient_tenant_permission`), or is a service key "
                "(`service_key_principal_not_supported`)."
            ),
            message="You do not have permission to manage flows.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_TENANT_PERMISSION,
            context={"auth_layer": "tenant_role"},
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def get_flow_execution_limits(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowExecutionLimitsPublic:
    require_flow_action(container.user(), FlowApiAction.EDIT)
    policy = await container.settings_service().get_flow_runtime_policy_resolved()
    return FlowExecutionLimitsPublic(
        default_step_timeout_seconds=policy.default_step_timeout_seconds,
        max_step_timeout_seconds=policy.max_step_timeout_seconds,
    )


__all__ = ["router"]
