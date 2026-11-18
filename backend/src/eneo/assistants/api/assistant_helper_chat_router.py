from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.assistants.application.assistant_helper_chat import (
    AssistantHelperChatAvailability,
    AssistantHelperChatErrorCode,
    AssistantHelperChatPublic,
    assistant_chat_availability,
    get_or_create_assistant_chat,
    start_assistant_conversation,
    update_assistant_chat,
)
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import NOT_PROVIDED, GeneralError
from eneo.server.dependencies.container import get_container

router = APIRouter()

_Changing = Annotated[
    Container, Depends(get_container(with_user=True, transaction_scope="function"))
]
_Reading = Annotated[Container, Depends(get_container(with_user=True))]

_ASSISTANT_ID = Annotated[
    UUID, Path(description="Identifier of the assistant the chat is about.")
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
_ACCESS_REASON = (
    "The helper chat checks the assistant's own read and edit access "
    "(AssistantService) and binds the chat to its person; a signed-in session "
    "only, so no API key reaches it."
)
_MODEL_ID_EXAMPLE = "00000000-0000-0000-0000-000000000402"
_CHAT_EXAMPLE = {
    "target_id": "00000000-0000-0000-0000-000000000001",
    "assistant_id": "00000000-0000-0000-0000-000000000201",
    "session_id": "00000000-0000-0000-0000-000000000301",
    "editing": False,
    "completion_model_id": None,
    "reasoning_effort": None,
    "default_completion_model_id": "00000000-0000-0000-0000-000000000401",
}


def _error(
    code: str,
    message: str,
    *,
    eneo_error_code: ErrorCodes = ErrorCodes.BAD_REQUEST,
    context: dict[str, object] | None = None,
) -> tuple[str, dict[str, object]]:
    """One documented refusal: its code and an example of its body."""
    value: dict[str, object] = {
        "message": message,
        "eneo_error_code": int(eneo_error_code),
        "code": str(code),
    }
    if context is not None:
        value["context"] = context
    return str(code), {"summary": message, "value": value}


def _response(
    description: str, *examples: tuple[str, dict[str, object]]
) -> dict[str, Any]:
    return {
        "model": GeneralError,
        "description": description,
        "content": {"application/json": {"examples": dict(examples)}},
    }


_FORBIDDEN = _response(
    "The caller may not edit the assistant, or it does not exist or cannot be "
    "read: the three answer alike. An API key gets 403 too "
    "(`session_auth_required`): the chat takes a signed-in session.",
    _error(
        AssistantHelperChatErrorCode.NO_EDIT_RIGHTS,
        "You do not have permission to edit this assistant.",
        eneo_error_code=ErrorCodes.UNAUTHORIZED,
        context={"resource_type": "assistant", "action": "update"},
    ),
)
_NOT_FOUND = _response(
    "The caller's chat is not this conversation, or the assistant was "
    "deleted meanwhile.",
    _error(
        "not_found",
        "Helper chat not found.",
        eneo_error_code=ErrorCodes.NOT_FOUND,
    ),
)
_NOT_SUPPORTED = _error(
    AssistantHelperChatErrorCode.NOT_SUPPORTED,
    "This assistant is configured elsewhere, so it has no helper chat.",
)
_NO_MODEL = _error(
    AssistantHelperChatErrorCode.NO_MODEL,
    "The space has no model that supports tools for the helper chat.",
)


class AssistantHelperChatUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "completion_model_id": _MODEL_ID_EXAMPLE,
                "reasoning_effort": "high",
            }
        },
    )
    editing: bool | None = Field(
        default=None, description="Turn edit mode on (true) or off (false)."
    )
    completion_model_id: UUID | None = Field(
        default=None,
        description=(
            "The model this chat answers with: one enabled in the assistant's "
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
    def _one_change(self) -> "AssistantHelperChatUpdateRequest":
        sent = self.model_fields_set
        if not sent & {"editing", "completion_model_id", "reasoning_effort"}:
            raise ValueError("Send editing, completion_model_id or reasoning_effort.")
        if "editing" in sent and self.editing is None:
            raise ValueError("editing must be true or false.")
        return self


@router.post(
    "/{id}/helper-chat/",
    response_model=AssistantHelperChatPublic,
    operation_id="get_or_create_assistant_helper_chat",
    summary="Open Assistant Helper Chat",
    description=(
        "Open the caller's helper chat on this assistant, creating it on first "
        "use. The chat is an ordinary conversation with a hidden assistant of "
        "the caller's own in the assistant's space, whose tools reach only "
        "this assistant; send its questions to `assistant_id`. Each user has "
        "one chat per assistant; calling again returns it with its current "
        "conversation and gives its assistant the current instructions and "
        "the model in force: the caller's own choice, else the organisation's "
        "default for helper chats when the space allows it, else the space's "
        "default among models that support tools. A new chat starts in view "
        "mode. Refused for an assistant the caller may not edit and for one "
        "configured elsewhere (a helper chat's own, a help assistant, a flow "
        "step's)."
    ),
    responses={
        200: {"content": {"application/json": {"example": _CHAT_EXAMPLE}}},
        400: _response(
            "The assistant is configured elsewhere, or its space has no model "
            "the chat can use.",
            _NOT_SUPPORTED,
            _NO_MODEL,
        ),
        403: _FORBIDDEN,
        404: _NOT_FOUND,
    },
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=_ACCESS_REASON,
)
async def open_assistant_helper_chat(
    id: _ASSISTANT_ID, request: Request, container: _Changing
) -> AssistantHelperChatPublic:
    return await get_or_create_assistant_chat(
        container, assistant_id=id, request=request
    )


@router.patch(
    "/{id}/helper-chat/{session_id}/",
    response_model=AssistantHelperChatPublic,
    operation_id="update_assistant_helper_chat",
    summary="Update Assistant Helper Chat",
    description=(
        "Turn the helper chat's edit mode on or off, or choose its model or "
        "reasoning effort. Turning edit mode on needs edit access to the "
        "assistant. Turning it on after the configured pause without a "
        "question or mode change starts a new conversation: the response then "
        "carries the new `session_id`. A model is checked like an assistant's "
        "model (enabled in the space and meeting its classification) and must "
        "support tools; null returns to the default. The chat's assistant "
        "follows the change before the response."
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
        400: _response(
            "The model or reasoning effort cannot be used by this chat.",
            _error(
                AssistantHelperChatErrorCode.MODEL_NOT_IN_SPACE,
                "The model is not enabled in the assistant's space.",
                context={"completion_model_id": _MODEL_ID_EXAMPLE},
            ),
            _error(
                AssistantHelperChatErrorCode.MODEL_BELOW_CLASSIFICATION,
                "The model's security classification is below the space's.",
                context={"completion_model_id": _MODEL_ID_EXAMPLE},
            ),
            _error(
                AssistantHelperChatErrorCode.MODEL_WITHOUT_TOOLS,
                "The helper chat needs a model that supports tools.",
                context={"completion_model_id": _MODEL_ID_EXAMPLE},
            ),
            _error(
                AssistantHelperChatErrorCode.REASONING_EFFORT_UNSUPPORTED,
                "The chat's model does not offer this reasoning effort.",
                context={
                    "reasoning_effort": "max",
                    "completion_model_id": _MODEL_ID_EXAMPLE,
                },
            ),
            _NO_MODEL,
            _NOT_SUPPORTED,
        ),
        403: _FORBIDDEN,
        404: _NOT_FOUND,
    },
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=_ACCESS_REASON,
)
async def change_assistant_helper_chat(
    id: _ASSISTANT_ID,
    session_id: _SESSION_ID,
    body: AssistantHelperChatUpdateRequest,
    container: _Changing,
) -> AssistantHelperChatPublic:
    sent = body.model_fields_set
    return await update_assistant_chat(
        container,
        assistant_id=id,
        session_id=session_id,
        editing=body.editing,
        completion_model_id=(
            body.completion_model_id if "completion_model_id" in sent else NOT_PROVIDED
        ),
        reasoning_effort=(
            body.reasoning_effort if "reasoning_effort" in sent else NOT_PROVIDED
        ),
    )


@router.post(
    "/{id}/helper-chat/{session_id}/conversations/",
    response_model=AssistantHelperChatPublic,
    operation_id="start_assistant_helper_chat_conversation",
    summary="Start a New Assistant Helper Chat Conversation",
    description=(
        "Leave the helper chat's current conversation and continue in a new, "
        "empty one with the same assistant, edit mode and model. Earlier "
        "conversations are kept for traceability but are never answered or "
        "sent to the model again: asking in one returns not found. The "
        "response carries the new `session_id`."
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
        400: _response("The assistant is configured elsewhere.", _NOT_SUPPORTED),
        403: _FORBIDDEN,
        404: _NOT_FOUND,
    },
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=_ACCESS_REASON,
)
async def start_assistant_helper_chat_conversation(
    id: _ASSISTANT_ID, session_id: _SESSION_ID, container: _Changing
) -> AssistantHelperChatPublic:
    return await start_assistant_conversation(
        container, assistant_id=id, session_id=session_id
    )


@router.get(
    "/{id}/helper-chat/availability",
    response_model=AssistantHelperChatAvailability,
    operation_id="get_assistant_helper_chat_availability",
    summary="Assistant Helper Chat Availability",
    description=(
        "Whether opening the caller's helper chat on this assistant would "
        "succeed, and if not why, by the same checks the open endpoint makes. "
        "Creates and changes nothing. An assistant that does not exist or "
        "cannot be read answers `no_edit_rights`, like one the caller may not "
        "edit."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "available": {
                            "summary": "The chat can be opened",
                            "value": {"available": True, "reason": None},
                        },
                        "no_edit_rights": {
                            "summary": "The caller may not edit the assistant",
                            "value": {"available": False, "reason": "no_edit_rights"},
                        },
                    }
                }
            }
        },
        403: _response(
            "Called with an API key: the chat takes a signed-in session.",
            _error(
                "session_auth_required",
                "This endpoint requires a session token.",
                eneo_error_code=ErrorCodes.UNAUTHORIZED,
            ),
        ),
    },
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=_ACCESS_REASON,
)
async def get_assistant_helper_chat_availability(
    id: _ASSISTANT_ID, request: Request, container: _Reading
) -> AssistantHelperChatAvailability:
    return await assistant_chat_availability(
        container, assistant_id=id, request=request
    )


__all__ = ["router"]
