from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.api.flow_assistant_router import require_flow_assistant_read_access
from eneo.flows.api.flow_tool_options_models import (
    FLOW_TOOL_OPTIONS_EXAMPLE,
    FlowToolOptionsPublic,
)
from eneo.flows.application.flow_tool_options import (
    FLOW_TOOL_OPTIONS_MAX_COUNT,
    FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES,
    TOOL_OPTIONS_TOO_LARGE_MESSAGE,
)
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import get_container

router = APIRouter()


@router.get(
    "/{id}/tool-options",
    response_model=FlowToolOptionsPublic,
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_tool_options",
    summary="List Tool Options",
    description=(
        "List the tools of the MCP servers the flow's space has activated, "
        "with the approved description and input schema of each. A tool that "
        "a level of the MCP decision refuses is listed on purpose, with the "
        "`refusal` that names the level, so an author can ask the person it "
        "names; only the tools of servers that are not general ones (a "
        "capability provider or one of Eneo's own servers), which no "
        "administrator can make usable by a flow, are left out, switched on "
        "or not. A `refusal` "
        "of null means that no level of that decision refuses the tool now: "
        "publish also requires the approved input schema to be a valid JSON "
        "Schema (`typed_io_tool_invalid_schema`) and checks the step's "
        "security classification, which this list does not judge, and the "
        "decision is asked again at publish and at run. A tool a step already "
        "uses is absent when its server is no longer activated in the space. "
        "A personal space has no MCP servers, so its list is empty; publish "
        "refuses a tool step there with `space_is_personal`. It needs the "
        "permission to edit flows in the space, checked on the space read "
        "without any MCP server's tools. The answer is not paged: one database "
        "statement reads the list in its order, and when the tools number more "
        f"than {FLOW_TOOL_OPTIONS_MAX_COUNT} or the counted text of "
        "them (the server name, the tool name, the approved description and the "
        "approved input schema as its JSON text, which it returns, and the "
        "server address, which it does not) takes more than "
        f"{FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES} bytes, it returns them only up "
        "to the first tool past the bound, and the list is refused with 413 "
        "`flow_tool_options_too_large`, never cut short."
    ),
    responses={
        200: {
            "description": (
                "The tools of the space; a null `refusal` means no level of the "
                "MCP decision refuses the tool now."
            ),
            "content": {"application/json": {"example": FLOW_TOOL_OPTIONS_EXAMPLE}},
        },
        403: error_response(
            description="Caller lacks permission to edit flows in this space.",
            message="You do not have permission to edit flows in this space.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
        ),
        413: error_response(
            description=(
                "`flow_tool_options_too_large`: the listed tools exceed the "
                "list's tool count or text byte limit; nothing is listed."
            ),
            message=TOOL_OPTIONS_TOO_LARGE_MESSAGE,
            eneo_error_code=ErrorCodes.FILE_TOO_LARGE,
            code=FlowApiErrorCode.TOOL_OPTIONS_TOO_LARGE,
            context={
                "max_tool_count": FLOW_TOOL_OPTIONS_MAX_COUNT,
                "max_text_bytes": FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES,
            },
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def list_flow_tool_options(
    id: Annotated[UUID, Path(description="Identifier of the draft flow.")],
    request: Request,
    container: Container = Depends(
        get_container(with_user=True, with_module_user=True)
    ),
):
    # An authoring aid: it is for the person who edits the flow's steps, so it
    # asks for the permission to author.
    await require_flow_assistant_read_access(request, container, flow_id=id)
    options = await container.flow_service().list_tool_options(flow_id=id)
    return FlowToolOptionsPublic.from_options(options)


__all__ = ["router"]
