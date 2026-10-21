from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.application.flow_authoring_chat import (
    FlowAuthoringChatPublic,
    get_or_create_authoring_chat,
    set_authoring_mode,
)
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.main.container.container import Container
from eneo.main.models import GeneralError
from eneo.server.dependencies.container import get_container

router = APIRouter(
    responses={
        403: {
            "model": GeneralError,
            "description": "The caller cannot manage this flow or chat.",
        },
        404: {
            "model": GeneralError,
            "description": "Flow or chat not found in the caller scope.",
        },
        400: {
            "model": GeneralError,
            "description": "Invalid configuration or stale revision.",
        },
    }
)
_Container = Annotated[
    Container, Depends(get_container(with_user=True, transaction_scope="function"))
]


class FlowAuthoringModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    editing: bool


@router.post(
    "/{id}/authoring-chat/",
    response_model=FlowAuthoringChatPublic,
    operation_id="get_or_create_flow_authoring_chat",
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def create_authoring_chat(
    id: UUID, request: Request, container: _Container
) -> FlowAuthoringChatPublic:
    return await get_or_create_authoring_chat(container, flow_id=id, request=request)


@router.patch(
    "/{id}/authoring-chat/{session_id}/",
    response_model=FlowAuthoringChatPublic,
    operation_id="set_flow_authoring_mode",
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def change_authoring_mode(
    id: UUID, session_id: UUID, body: FlowAuthoringModeRequest, container: _Container
) -> FlowAuthoringChatPublic:
    return await set_authoring_mode(
        container,
        flow_id=id,
        session_id=session_id,
        editing=body.editing,
        expected_revision=body.expected_revision,
    )
