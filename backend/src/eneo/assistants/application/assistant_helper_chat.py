"""The assistant as the target of a helper chat: the chat beside the assistant
editor.

A person who may edit an assistant has one chat on it: a hidden assistant of
their own in the assistant's space and the conversation that is current. The
package ``helper_chats`` runs it. This module gives that package the
assistant's access rules, refusals, persona and tools (``ASSISTANT_TARGET``)
and keeps the assistant's own entry points.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import aliased

from eneo.assistants.assistant import AssistantOrigin
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import get_scope_filter
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.helper_chats_table import HelperChats
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.domain.flow_authoring_chat_policy import (
    resolve_flow_authoring_chat_model_id,
)
from eneo.helper_chats.application import helper_chat_service
from eneo.helper_chats.application.helper_chat_service import (
    HelperChatConversationPublic,
    OpenedChat,
)
from eneo.helper_chats.personas.assistant import ASSISTANT_INSTRUCTIONS
from eneo.helper_chats.personas.organisation_guidance import (
    with_organisation_guidance,
)
from eneo.helper_chats.policy import HelperChatPolicy, resolve_helper_chat_policy
from eneo.helper_chats.targets import (
    HelperChatAudit,
    HelperChatAuditEvent,
    HelperChatTargetType,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.models import NOT_PROVIDED, NotProvided, ResourcePermission

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer


class AssistantHelperChatErrorCode(StrEnum):
    """The codes of the chat's refusals, so a client can tell them apart."""

    NO_EDIT_RIGHTS = "helper_chat_no_edit_rights"
    NOT_SUPPORTED = "helper_chat_not_supported"
    NOT_EDITING = "helper_chat_not_editing"
    NO_MODES = "helper_chat_no_modes"
    NO_MODEL = "helper_chat_no_model"
    MODEL_WITHOUT_TOOLS = "helper_chat_model_without_tools"
    MODEL_BELOW_CLASSIFICATION = "helper_chat_model_below_classification"
    MODEL_NOT_IN_SPACE = "helper_chat_model_not_in_space"
    REASONING_EFFORT_UNSUPPORTED = "helper_chat_reasoning_effort_unsupported"
    DISABLED = "helper_chat_disabled"


# Why the person gets no chat on an assistant: the organisation has turned the
# chat off; the space has no model the chat can answer with; the person may
# not edit the assistant, or it does not exist or cannot be read, which are
# told apart from nothing else; or the assistant is configured elsewhere (a
# helper chat's own, a help assistant, a flow step's).
UnavailableReason = Literal["disabled", "no_model", "no_edit_rights", "not_supported"]


class AssistantHelperChatPublic(BaseModel):
    target_id: UUID = Field(description="The assistant the chat is about.")
    assistant_id: UUID = Field(
        description=(
            "The chat's own assistant, hidden from every list: the chat's "
            "questions are sent to it."
        )
    )
    session_id: UUID = Field(
        description=(
            "The chat's current conversation. Starting a new conversation, or "
            "opening with `fresh_start`, replaces it; earlier conversations "
            "are kept and listed for their person but never answered again."
        )
    )
    editing: bool = Field(
        description=(
            "Always false: the chat on an assistant has one mode. It proposes "
            "each change for the person to apply and never changes the "
            "assistant itself."
        )
    )
    completion_model_id: UUID | None = Field(
        default=None,
        description=(
            "The model the caller chose for this chat; null follows the default "
            "(`default_completion_model_id`)."
        ),
    )
    reasoning_effort: str | None = Field(
        default=None,
        description=(
            "The reasoning effort the caller chose; null uses the model's own "
            "default. Applied only when the chat's model offers that level."
        ),
    )
    default_completion_model_id: UUID | None = Field(
        default=None,
        description=(
            "The model the chat answers with while `completion_model_id` is "
            "null: the organisation's default for helper chats when this space "
            "allows it, else the space's default among models that support tools."
        ),
    )


class AssistantHelperChatAvailability(BaseModel):
    available: bool = Field(
        description="Whether opening the chat on this assistant would succeed."
    )
    reason: UnavailableReason | None = Field(
        default=None,
        description=(
            "Why not: `disabled` when the organisation has turned the helper "
            "chat off (checked first); `no_model` when the space has no model "
            "that supports tools; `no_edit_rights` when the caller may not edit the "
            "assistant, which is also the answer for one that does not exist "
            "or cannot be read; `not_supported` for an assistant that is "
            "configured elsewhere (a helper chat's own, a help assistant or a "
            "flow step's). Null when available."
        ),
    )


def _policy(container: Container) -> HelperChatPolicy:
    """The caller's organisation's settings for the chat, as the caller was
    read for this request."""
    tenant = getattr(container.user(), "tenant", None)
    return resolve_helper_chat_policy(
        cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None))
    )


def scoped_request(space_id: UUID) -> Request:
    from eneo.internal_mcp.constants import ASSISTANT_SERVER_NAME
    from eneo.internal_mcp.foundation import request_for_bound_space

    return request_for_bound_space(space_id, server_name=ASSISTANT_SERVER_NAME)


def _in_scope(request: Request, assistant: Assistant) -> bool:
    """Whether ``assistant`` is inside the request's scope: for a bound chat,
    the chat's space."""
    scope = get_scope_filter(request)
    if scope.space_id is not None and scope.space_id != assistant.space_id:
        return False
    return scope.assistant_id is None or scope.assistant_id == assistant.id


async def _editable(
    container: Container, request: Request, target_id: UUID
) -> Assistant | UnavailableReason:
    """The assistant when the caller may edit it and a helper chat may be
    about it, else why not. Read and edit access are the assistant
    endpoints' own (``AssistantService.get_assistant`` and the permissions it
    gives), and an assistant the caller cannot reach answers as one they may
    not edit."""
    service = container.assistant_service()
    owner_id = await service.helper_chat_owner_id(target_id)
    if owner_id is not None:
        # A helper chat's own assistant is configured through its chat; for
        # anyone else it does not exist.
        return "not_supported" if owner_id == container.user().id else "no_edit_rights"
    try:
        assistant, permissions = await service.get_assistant(target_id)
    except (NotFoundException, UnauthorizedException):
        return "no_edit_rights"
    if not _in_scope(request, assistant):
        return "no_edit_rights"
    if (
        assistant.hidden
        or assistant.origin == AssistantOrigin.FLOW_MANAGED
        or await service.is_help_assistant(target_id)
    ):
        return "not_supported"
    if ResourcePermission.EDIT not in permissions:
        return "no_edit_rights"
    return assistant


class _AssistantChatRefusals:
    """The errors the assistant endpoints give for what the chat refuses."""

    def chat_not_found(self) -> Exception:
        return NotFoundException("Helper chat not found.")

    def target_not_found(self) -> Exception:
        return NotFoundException("Assistant not found.")

    def unavailable(self, reason: UnavailableReason) -> Exception:
        if reason == "disabled":
            return self.disabled()
        if reason == "not_supported":
            return BadRequestException(
                "This assistant is configured elsewhere, so it has no helper chat.",
                code=AssistantHelperChatErrorCode.NOT_SUPPORTED,
            )
        if reason == "no_model":
            return self.no_model()
        return UnauthorizedException(
            "You do not have permission to edit this assistant.",
            code=AssistantHelperChatErrorCode.NO_EDIT_RIGHTS,
            context={
                "resource_type": "assistant",
                "action": "update",
                "auth_layer": "domain_policy",
            },
        )

    def disabled(self) -> Exception:
        return UnauthorizedException(
            "Your organisation has turned off the helper chat.",
            code=AssistantHelperChatErrorCode.DISABLED,
        )

    def not_editing(self) -> Exception:
        return BadRequestException(
            "Turn on edit mode in the helper chat before changing this assistant.",
            code=AssistantHelperChatErrorCode.NOT_EDITING,
        )

    def no_modes(self) -> Exception:
        return BadRequestException(
            "The helper chat on an assistant has one mode, so its mode cannot be "
            "changed: it proposes each change, and the person applies it.",
            code=AssistantHelperChatErrorCode.NO_MODES,
        )

    def no_model(self) -> Exception:
        return BadRequestException(
            "The space has no model that supports tools for the helper chat.",
            code=AssistantHelperChatErrorCode.NO_MODEL,
        )

    def model_without_tools(self, model_id: UUID) -> Exception:
        return BadRequestException(
            "The helper chat needs a model that supports tools.",
            code=AssistantHelperChatErrorCode.MODEL_WITHOUT_TOOLS,
            context={"completion_model_id": str(model_id)},
        )

    def model_below_classification(self, model_id: UUID) -> Exception:
        return BadRequestException(
            "The model's security classification is below the space's.",
            code=AssistantHelperChatErrorCode.MODEL_BELOW_CLASSIFICATION,
            context={"completion_model_id": str(model_id)},
        )

    def model_not_in_space(self, model_id: UUID) -> Exception:
        return BadRequestException(
            "The model is not enabled in the assistant's space.",
            code=AssistantHelperChatErrorCode.MODEL_NOT_IN_SPACE,
            context={"completion_model_id": str(model_id)},
        )

    def reasoning_effort_unsupported(
        self, reasoning_effort: str, model_id: UUID
    ) -> Exception:
        return BadRequestException(
            "The chat's model does not offer this reasoning effort.",
            code=AssistantHelperChatErrorCode.REASONING_EFFORT_UNSUPPORTED,
            context={
                "reasoning_effort": reasoning_effort,
                "completion_model_id": str(model_id),
            },
        )


# The target assistant, apart from the chat's own hidden assistant that the
# chat's loader joins as ``Assistants``.
_TargetAssistant = aliased(Assistants, name="helper_chat_target_assistant")
_TargetSpace = aliased(Spaces, name="helper_chat_target_space")


class _AssistantTarget:
    """An assistant's chat: it reads the assistant while the person may read
    it, and is opened while the person may edit it. It has one mode: it
    proposes each change for the person to apply, publishes or unpublishes
    only once the person approves the call, and never changes the assistant
    itself. The organisation's settings (``helper_chats.policy``) turn the
    chat off and add their guidance to its persona."""

    target_type = HelperChatTargetType.ASSISTANT
    has_modes = False
    audit = HelperChatAudit(
        entity_type=EntityType.ASSISTANT,
        chat_created=HelperChatAuditEvent(
            ActionType.HELPER_CHAT_CREATED, "Created a helper chat on an assistant."
        ),
        mode_changed=HelperChatAuditEvent(
            ActionType.HELPER_CHAT_MODE_CHANGED,
            "Changed edit mode in a helper chat on an assistant.",
        ),
        conversation_started=HelperChatAuditEvent(
            ActionType.HELPER_CHAT_CONVERSATION_STARTED,
            "Started a new conversation in a helper chat on an assistant.",
        ),
        model_changed=HelperChatAuditEvent(
            ActionType.HELPER_CHAT_MODEL_CHANGED,
            "Changed the model of a helper chat on an assistant.",
        ),
    )
    refusals = _AssistantChatRefusals()

    def instructions(self, container: Container) -> str:
        return with_organisation_guidance(
            ASSISTANT_INSTRUCTIONS, _policy(container).guidance
        )

    async def require_available(self, container: Container) -> None:
        # Turned off, an existing chat can be neither opened nor continued: its
        # turns and tool calls load it through here.
        if not _policy(container).enabled:
            raise self.refusals.disabled()

    def target_exists(self, tenant_id: UUID) -> sa.ColumnElement[bool]:
        return sa.exists().where(
            _TargetAssistant.id == HelperChats.target_id,
            _TargetAssistant.space_id == HelperChats.space_id,
            _TargetSpace.id == _TargetAssistant.space_id,
            _TargetSpace.tenant_id == tenant_id,
        )

    def scoped_request(self, space_id: UUID) -> Request:
        return scoped_request(space_id)

    async def require_read(
        self, container: Container, request: Request, target_id: UUID
    ) -> Assistant:
        try:
            assistant, _ = await container.assistant_service().get_assistant(target_id)
        except (NotFoundException, UnauthorizedException):
            raise self.refusals.chat_not_found() from None
        if not _in_scope(request, assistant):
            raise self.refusals.chat_not_found()
        return assistant

    async def require_edit(
        self, container: Container, request: Request, target_id: UUID
    ) -> Assistant:
        editable = await _editable(container, request, target_id)
        if isinstance(editable, str):
            raise self.refusals.unavailable(editable)
        return editable

    async def load(self, container: Container, target_id: UUID) -> Assistant:
        assistant, _ = await container.assistant_service().get_assistant(target_id)
        return assistant

    def space_id(self, record: Assistant) -> UUID:
        return record.space_id

    def name(self, record: Assistant) -> str:
        return record.name

    async def lock(self, container: Container, target_id: UUID) -> bool:
        return await container.assistant_service().lock_assistant(target_id)

    async def fence_mode_change(
        self, container: Container, target_id: UUID, expected_revision: int | None
    ) -> None:
        return None

    def changeable(self, record: Assistant) -> bool:
        return True

    def require_changeable(self, record: Assistant) -> None:
        return None

    def starts_in_edit_mode(self, record: Assistant) -> bool:
        # The chat has no edit mode.
        return False

    def idle_after(self) -> timedelta:
        return timedelta(minutes=get_settings().flow_authoring_chat_idle_minutes)

    def organisation_default_model_id(self, container: Container) -> UUID | None:
        # One organisation default serves every helper chat.
        tenant = getattr(container.user(), "tenant", None)
        return resolve_flow_authoring_chat_model_id(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None))
        )

    async def build_tool_server(
        self, *, token: str, tenant_id: UUID, editing: bool
    ) -> MCPServer:
        # One mode, so every turn gets the same tools whatever ``editing``.
        from eneo.internal_mcp.assistant_settings import (
            build_assistant_settings_mcp_server,
        )

        return await build_assistant_settings_mcp_server(
            token=token, tenant_id=tenant_id
        )


ASSISTANT_TARGET = _AssistantTarget()


# --- Entry points -----------------------------------------------------------


def _public(opened: OpenedChat) -> AssistantHelperChatPublic:
    chat = opened.chat
    return AssistantHelperChatPublic(
        target_id=chat.target_id,
        assistant_id=chat.assistant_id,
        session_id=chat.session_id,
        # False whatever the row holds: the chat has no edit mode.
        editing=helper_chat_service.in_edit_mode(ASSISTANT_TARGET, chat),
        completion_model_id=chat.completion_model_id,
        reasoning_effort=chat.reasoning_effort,
        default_completion_model_id=opened.default_completion_model_id,
    )


async def get_or_create_assistant_chat(
    container: Container,
    *,
    assistant_id: UUID,
    request: Request,
    fresh_start: bool = False,
) -> AssistantHelperChatPublic:
    """The caller's chat, made on first use; with ``fresh_start`` on a new,
    empty conversation (``helper_chat_service.get_or_create_chat``)."""
    return _public(
        await helper_chat_service.get_or_create_chat(
            container,
            ASSISTANT_TARGET,
            target_id=assistant_id,
            request=request,
            fresh_start=fresh_start,
        )
    )


async def list_assistant_conversations(
    container: Container, *, assistant_id: UUID, request: Request
) -> list[HelperChatConversationPublic]:
    """The caller's conversations in their chat on the assistant that hold a
    question, the latest question first."""
    return await helper_chat_service.list_conversations(
        container, ASSISTANT_TARGET, target_id=assistant_id, request=request
    )


async def update_assistant_chat(
    container: Container,
    *,
    assistant_id: UUID,
    session_id: UUID,
    editing: bool | None = None,
    completion_model_id: UUID | None | NotProvided = NOT_PROVIDED,
    reasoning_effort: str | None | NotProvided = NOT_PROVIDED,
) -> AssistantHelperChatPublic:
    """Change the chat's model or reasoning effort, then bring its assistant
    in line. The chat has one mode, so a request that sends ``editing`` is
    refused (``helper_chat_no_modes``)."""
    return _public(
        await helper_chat_service.update_chat(
            container,
            ASSISTANT_TARGET,
            target_id=assistant_id,
            session_id=session_id,
            editing=editing,
            completion_model_id=completion_model_id,
            reasoning_effort=reasoning_effort,
        )
    )


async def start_assistant_conversation(
    container: Container, *, assistant_id: UUID, session_id: UUID
) -> AssistantHelperChatPublic:
    """Leave the current conversation behind and continue in a new one."""
    return _public(
        await helper_chat_service.start_new_conversation(
            container, ASSISTANT_TARGET, target_id=assistant_id, session_id=session_id
        )
    )


def _unavailable(reason: UnavailableReason) -> AssistantHelperChatAvailability:
    return AssistantHelperChatAvailability(available=False, reason=reason)


async def assistant_chat_availability(
    container: Container, *, assistant_id: UUID, request: Request
) -> AssistantHelperChatAvailability:
    """Whether opening the caller's chat on the assistant would succeed, by
    the gates ``get_or_create_assistant_chat`` passes, without creating or
    changing anything."""
    if not _policy(container).enabled:
        return _unavailable("disabled")
    editable = await _editable(container, request, assistant_id)
    if isinstance(editable, str):
        return _unavailable(editable)
    if not await helper_chat_service.chat_exists(
        container, ASSISTANT_TARGET, target_id=assistant_id
    ):
        # A first chat creates the person's hidden assistant in the space.
        access = await container.space_service().get_space_access_facts(
            editable.space_id
        )
        if (
            not container.actor_manager()
            .get_space_actor(access)
            .can_create_assistants()
        ):
            return _unavailable("no_edit_rights")
    space = await container.space_repo().one(id=editable.space_id)
    if (
        helper_chat_service.chat_default_model(container, ASSISTANT_TARGET, space)
        is None
    ):
        return _unavailable("no_model")
    return AssistantHelperChatAvailability(available=True)
