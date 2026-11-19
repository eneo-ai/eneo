from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.application.flow_authoring_chat import (
    FlowAuthoringChatPublic,
    get_or_create_authoring_chat,
    list_authoring_conversations,
    start_authoring_conversation,
    update_authoring_chat,
)
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.helper_chats.application.helper_chat_service import (
    CONVERSATION_LIST_LIMIT,
    HelperChatConversationPublic,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import NOT_PROVIDED, PaginatedResponse
from eneo.server.dependencies.container import get_container

_Container = Annotated[
    Container, Depends(get_container(with_user=True, transaction_scope="function"))
]
_Reading = Annotated[Container, Depends(get_container(with_user=True))]


async def _require_user_for_chat(container: _Container) -> None:
    """``require_user_for_creation`` on the user the route's one
    authentication resolved: opening a chat makes its conversation, which a
    service key cannot own, and the flows feature gate still runs inside that
    authentication."""
    await require_user_for_creation(container.user())


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
    "completion_model_id": None,
    "reasoning_effort": None,
    "default_completion_model_id": "00000000-0000-0000-0000-000000000401",
}
_MODEL_ID_EXAMPLE = "00000000-0000-0000-0000-000000000402"
_CONVERSATIONS_EXAMPLE = {
    "items": [
        {
            "session_id": "00000000-0000-0000-0000-000000000301",
            "title": "Lägg till ett steg efter @[Steg 1](step:1)",
            "started_at": "2026-11-19T09:12:00Z",
            "last_asked_at": "2026-11-19T09:20:41Z",
            "current": True,
        },
        {
            "session_id": "00000000-0000-0000-0000-000000000300",
            "title": "Bygg ett flöde som sammanfattar ett protokoll",
            "started_at": "2026-11-18T14:02:10Z",
            "last_asked_at": "2026-11-18T14:05:37Z",
            "current": False,
        },
    ],
    "count": 2,
}
_FRESH_START = Annotated[
    bool,
    Query(
        description=(
            "Open on a new, empty conversation: a current conversation that "
            "holds a question is left for a new one, as starting a new "
            "conversation does, and an empty one is kept as it is. The mode "
            "and the model choice stay."
        )
    ),
]
_SESSION_ID = Annotated[
    UUID,
    Path(
        description=(
            "Identifier of the chat's current conversation, as the chat last "
            "returned it."
        )
    ),
]


def _refusal(code: FlowApiErrorCode, summary: str, message: str) -> dict[str, object]:
    return {
        "summary": summary,
        "value": {
            "message": message,
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": code.value,
            "context": {"completion_model_id": _MODEL_ID_EXAMPLE},
        },
    }


router = APIRouter()


class FlowAuthoringChatUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "completion_model_id": _MODEL_ID_EXAMPLE,
                "reasoning_effort": "high",
            }
        },
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description=(
            "The draft revision the caller last read. Required with `editing`: "
            "a mode change against a stale draft is refused."
        ),
    )
    editing: bool | None = Field(
        default=None, description="Turn edit mode on (true) or off (false)."
    )
    completion_model_id: UUID | None = Field(
        default=None,
        description=(
            "The model this chat answers with: one enabled in the flow's "
            "space, meeting its security classification, that supports tools. "
            "Null returns to the default; omit to keep the current choice."
        ),
    )
    reasoning_effort: str | None = Field(
        default=None,
        description=(
            "A reasoning effort the chat's model offers "
            "(`supported_model_kwargs.reasoning_effort`). Null uses the "
            "model's default; omit to keep the current choice."
        ),
    )

    @model_validator(mode="after")
    def _one_change(self) -> "FlowAuthoringChatUpdateRequest":
        sent = self.model_fields_set
        if not sent & {"editing", "completion_model_id", "reasoning_effort"}:
            raise ValueError("Send editing, completion_model_id or reasoning_effort.")
        if "editing" in sent:
            if self.editing is None:
                raise ValueError("editing must be true or false.")
            if self.expected_revision is None:
                raise ValueError("Send expected_revision with editing.")
        return self


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
        "edit mode. Each user has one chat per flow; calling again returns it "
        "with its current conversation, or with `fresh_start` on a new, empty "
        "one (an empty current conversation is kept, so repeated opens leave "
        "no empty conversation behind), and gives its assistant the current "
        "instructions and the model in force: the caller's own choice, else the "
        "organisation's default for flow chats when the space allows it, else "
        "the space's default among models that support tools."
    ),
    responses={
        200: {"content": {"application/json": {"example": _CHAT_EXAMPLE}}},
        400: error_response(
            description="The space has no model that the chat can use.",
            message="Choose a default model that supports tools for this space.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.AUTHORING_CHAT_NO_MODEL,
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
    id: _FLOW_ID,
    request: Request,
    container: _Container,
    _user_for_creation: Annotated[None, Depends(_require_user_for_chat)],
    fresh_start: _FRESH_START = False,
) -> FlowAuthoringChatPublic:
    return await get_or_create_authoring_chat(
        container, flow_id=id, request=request, fresh_start=fresh_start
    )


@router.patch(
    "/{id}/authoring-chat/{session_id}/",
    response_model=FlowAuthoringChatPublic,
    operation_id="update_flow_authoring_chat",
    summary="Update Flow Authoring Chat",
    description=(
        "Turn the authoring chat's edit mode on or off, or choose its model. In "
        "edit mode the chat's tools may change the draft through the same "
        "validation, permissions, classification and audit as the editor; "
        "leaving it waits for a change in progress and stops the next one. A "
        "mode change is fenced on the draft revision the caller last read, so "
        "one made against a stale draft is refused with `stale_revision`. "
        "Turning edit mode on after the configured pause without a question or "
        "mode change starts a new conversation: the response then carries the "
        "new `session_id`. A model is checked like an assistant's model (enabled "
        "in the space and meeting its classification) and must support tools; "
        "null returns to the default. The chat's assistant follows the change "
        "before the response."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        **_CHAT_EXAMPLE,
                        "editing": True,
                        "completion_model_id": _MODEL_ID_EXAMPLE,
                        "reasoning_effort": "high",
                    }
                }
            }
        },
        400: error_response(
            description=(
                "The draft moved on since `expected_revision`, or the model or "
                "reasoning effort cannot be used by this chat."
            ),
            examples={
                FlowApiErrorCode.STALE_REVISION.value: {
                    "summary": "The draft changed since it was read",
                    "value": {
                        "message": "The flow draft changed since it was read.",
                        "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
                        "code": FlowApiErrorCode.STALE_REVISION.value,
                    },
                },
                FlowApiErrorCode.AUTHORING_MODEL_NOT_IN_SPACE.value: _refusal(
                    FlowApiErrorCode.AUTHORING_MODEL_NOT_IN_SPACE,
                    "The model is not enabled in the space",
                    "The model is not enabled in the flow's space.",
                ),
                FlowApiErrorCode.AUTHORING_MODEL_BELOW_CLASSIFICATION.value: _refusal(
                    FlowApiErrorCode.AUTHORING_MODEL_BELOW_CLASSIFICATION,
                    "The model is below the space's classification",
                    "The model's security classification is below the space's.",
                ),
                FlowApiErrorCode.AUTHORING_MODEL_WITHOUT_TOOLS.value: _refusal(
                    FlowApiErrorCode.AUTHORING_MODEL_WITHOUT_TOOLS,
                    "The model does not support tools",
                    "The flow chat needs a model that supports tools.",
                ),
                FlowApiErrorCode.AUTHORING_REASONING_EFFORT_UNSUPPORTED.value: {
                    "summary": "The model does not offer the reasoning effort",
                    "value": {
                        "message": (
                            "The chat's model does not offer this reasoning effort."
                        ),
                        "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
                        "code": (
                            FlowApiErrorCode.AUTHORING_REASONING_EFFORT_UNSUPPORTED.value
                        ),
                        "context": {
                            "reasoning_effort": "max",
                            "completion_model_id": _MODEL_ID_EXAMPLE,
                        },
                    },
                },
            },
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
async def change_authoring_chat(
    id: _FLOW_ID,
    session_id: _SESSION_ID,
    body: FlowAuthoringChatUpdateRequest,
    container: _Container,
) -> FlowAuthoringChatPublic:
    sent = body.model_fields_set
    return await update_authoring_chat(
        container,
        flow_id=id,
        session_id=session_id,
        editing=body.editing,
        expected_revision=body.expected_revision,
        completion_model_id=(
            body.completion_model_id if "completion_model_id" in sent else NOT_PROVIDED
        ),
        reasoning_effort=(
            body.reasoning_effort if "reasoning_effort" in sent else NOT_PROVIDED
        ),
    )


@router.post(
    "/{id}/authoring-chat/{session_id}/conversations/",
    response_model=FlowAuthoringChatPublic,
    operation_id="start_flow_authoring_conversation",
    summary="Start a New Flow Authoring Conversation",
    description=(
        "Leave the chat's current conversation and continue in a new, empty one "
        "with the same assistant, edit mode and model. Earlier conversations are "
        "kept for traceability and listed for their person (`GET "
        ".../authoring-chat/conversations/`), but are never answered or sent "
        "to the model again: asking in one returns not found. The response "
        "carries the new "
        "`session_id`; the flow itself, its revisions and the audit log stay the "
        "record of what changed."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        **_CHAT_EXAMPLE,
                        "session_id": "00000000-0000-0000-0000-000000000302",
                    }
                }
            }
        },
        403: _FORBIDDEN,
        404: _NOT_FOUND,
    },
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def start_conversation(
    id: _FLOW_ID, session_id: _SESSION_ID, container: _Container
) -> FlowAuthoringChatPublic:
    return await start_authoring_conversation(
        container, flow_id=id, session_id=session_id
    )


@router.get(
    "/{id}/authoring-chat/conversations/",
    response_model=PaginatedResponse[HelperChatConversationPublic],
    operation_id="list_flow_authoring_conversations",
    summary="List Flow Authoring Conversations",
    description=(
        "The caller's conversations in their chat on this flow that hold a "
        "question, the latest question first, at most "
        f"{CONVERSATION_LIST_LIMIT}. Each names its first question as its "
        "title and says whether it is the chat's current conversation; read "
        "one with `GET /api/v1/conversations/{session_id}/`. Only the current "
        "conversation is ever answered. The checks are the open endpoint's, "
        "and a caller without a chat on the flow gets not found. Creates and "
        "changes nothing: a chat left in edit mode stays in it until it is "
        "opened or used."
    ),
    responses={
        200: {"content": {"application/json": {"example": _CONVERSATIONS_EXAMPLE}}},
        403: _FORBIDDEN,
        404: _NOT_FOUND,
    },
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def list_conversations(
    id: _FLOW_ID, request: Request, container: _Reading
) -> PaginatedResponse[HelperChatConversationPublic]:
    return PaginatedResponse(
        items=await list_authoring_conversations(container, flow_id=id, request=request)
    )


__all__ = ["router"]
