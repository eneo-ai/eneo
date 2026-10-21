from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.application.flow_authoring_chat import (
    FlowAuthoringChatPublic,
    get_or_create_authoring_chat,
    set_authoring_mode,
)
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import get_container

_Container = Annotated[
    Container, Depends(get_container(with_user=True, transaction_scope="function"))
]

_FLOW_ID = Annotated[UUID, Path(description="Identifier of the draft flow to edit.")]

_FORBIDDEN = error_response(
    description=(
        "The caller cannot edit this flow, or called with an API key: the "
        "authoring chat takes a signed-in session."
    ),
    message="You do not have permission to edit flows in this space.",
    eneo_error_code=ErrorCodes.UNAUTHORIZED,
    code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
    context={"auth_layer": "space_membership"},
)
_NOT_FOUND = error_response(
    description="The flow, or the caller's chat for it, is not in the caller's scope.",
    message="Flow authoring chat not found.",
    eneo_error_code=ErrorCodes.NOT_FOUND,
)

_CHAT_EXAMPLE = {
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "assistant_id": "00000000-0000-0000-0000-000000000201",
    "session_id": "00000000-0000-0000-0000-000000000301",
    "editing": False,
}


router = APIRouter()


class FlowAuthoringModeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"expected_revision": 4, "editing": True}},
    )
    expected_revision: int = Field(ge=0)
    editing: bool


@router.post(
    "/{id}/authoring-chat/",
    response_model=FlowAuthoringChatPublic,
    operation_id="get_or_create_flow_authoring_chat",
    summary="Open Flow Authoring Chat",
    description=(
        "Open the caller's chat for editing this flow with an assistant, creating "
        "it on first use. The chat is an ordinary conversation whose assistant "
        "reaches only this flow through its tools, and it starts in view mode: "
        "the tools read the flow but change nothing until the caller turns on "
        "edit mode. Each user has one chat per flow; calling again returns it."
    ),
    responses={
        200: {"content": {"application/json": {"example": _CHAT_EXAMPLE}}},
        400: error_response(
            description="The space has no default model that supports tools.",
            message="Choose a default model that supports tools for this space.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
        ),
        403: _FORBIDDEN,
        404: _NOT_FOUND,
    },
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def create_authoring_chat(
    id: _FLOW_ID, request: Request, container: _Container
) -> FlowAuthoringChatPublic:
    return await get_or_create_authoring_chat(container, flow_id=id, request=request)


@router.patch(
    "/{id}/authoring-chat/{session_id}/",
    response_model=FlowAuthoringChatPublic,
    operation_id="set_flow_authoring_mode",
    summary="Set Flow Authoring Mode",
    description=(
        "Turn the authoring chat's edit mode on or off. In edit mode the chat's "
        "tools may change the draft through the same validation, permissions, "
        "classification and audit as the editor; leaving it waits for a change "
        "in progress and stops the next one. The switch is fenced on the draft "
        "revision the caller last read, so a mode change made against a stale "
        "draft is refused with `stale_revision`."
    ),
    responses={
        200: {
            "content": {
                "application/json": {"example": {**_CHAT_EXAMPLE, "editing": True}}
            }
        },
        400: error_response(
            description="The draft moved on since `expected_revision`.",
            message="The flow draft changed since it was read.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.STALE_REVISION,
        ),
        403: _FORBIDDEN,
        404: _NOT_FOUND,
    },
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def change_authoring_mode(
    id: _FLOW_ID,
    session_id: Annotated[
        UUID, Path(description="Identifier of the chat's conversation.")
    ],
    body: FlowAuthoringModeRequest,
    container: _Container,
) -> FlowAuthoringChatPublic:
    return await set_authoring_mode(
        container,
        flow_id=id,
        session_id=session_id,
        editing=body.editing,
        expected_revision=body.expected_revision,
    )


__all__ = ["router"]
