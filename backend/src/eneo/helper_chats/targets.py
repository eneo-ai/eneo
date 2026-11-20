"""What a helper chat asks of the thing it helps with.

A helper chat binds a person's hidden assistant and current conversation to
one target. The mechanics (``helper_chats.application.helper_chat_service``)
are the same for every target; each member of ``HelperChatTarget`` is a
question about the target that only the target can answer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, TypeVar
from uuid import UUID

import sqlalchemy as sa

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType

if TYPE_CHECKING:
    from fastapi import Request

    from eneo.main.container.container import Container
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer


class HelperChatTargetType(StrEnum):
    """The kinds of target, as ``helper_chats.target_type`` stores them."""

    FLOW = "flow"
    ASSISTANT = "assistant"


RecordT = TypeVar("RecordT")
# The modes only take a target, so they may take a more general one.
RecordInT = TypeVar("RecordInT", contravariant=True)


@dataclass(frozen=True)
class HelperChatAuditEvent:
    action: ActionType
    description: str


@dataclass(frozen=True)
class HelperChatAudit:
    """How the audit log names what happens to a target's chats. Every entry
    has the person as actor and the target as its entity. An event a target
    has no action for (None) is not recorded."""

    entity_type: EntityType
    chat_created: HelperChatAuditEvent | None
    conversation_started: HelperChatAuditEvent | None
    model_changed: HelperChatAuditEvent | None


class HelperChatRefusals(Protocol):
    """The errors the target's API gives when the mechanics refuse."""

    def chat_not_found(self) -> Exception: ...

    def target_not_found(self) -> Exception: ...

    def no_model(self) -> Exception: ...

    def model_without_tools(self, model_id: UUID) -> Exception: ...

    def model_below_classification(self, model_id: UUID) -> Exception: ...

    def model_not_in_space(self, model_id: UUID) -> Exception: ...

    def reasoning_effort_unsupported(
        self, reasoning_effort: str, model_id: UUID
    ) -> Exception: ...


class HelperChatModes(Protocol[RecordInT]):
    """What a target whose chat the person switches between "Fråga" and
    "Redigera" adds. Only such a chat is ever in edit mode, where the chat
    itself may write to the target."""

    @property
    def mode_changed(self) -> HelperChatAuditEvent:
        """The audit entry of a change of edit mode, the person's or the
        pause's."""
        ...

    def not_editing(self) -> Exception:
        """The refusal of a change the chat makes outside edit mode."""
        ...

    def starts_in_edit_mode(self, record: RecordInT) -> bool:
        """Whether a new chat on the target starts in edit mode."""
        ...

    def idle_after(self) -> timedelta:
        """How long a conversation goes without a question or mode change
        before edit mode is left and turning it on starts a new one."""
        ...

    async def fence_mode_change(
        self, container: Container, target_id: UUID, expected_revision: int | None
    ) -> None:
        """Refuse a change of edit mode made against a target that changed
        since the caller last read it."""
        ...


class HelperChatTarget(Protocol[RecordT]):
    """One kind of target. ``RecordT`` is the target as its own package loads
    it; the audit entries name it."""

    @property
    def target_type(self) -> HelperChatTargetType: ...

    @property
    def modes(self) -> HelperChatModes[RecordT] | None:
        """The chat's two modes; None for a target whose chat has one. That
        chat is never in edit mode: it proposes each change for the person
        to apply."""
        ...

    @property
    def tool_runtime(self) -> bool:
        """Whether the chat's assistant works with the tool runtime: its
        functions as far as the chat's space offers them, and an uploaded
        file looked up through the files tool. A chat without it has its
        target's tools only, and reads an upload's text with the question."""
        ...

    def instructions(self, container: Container) -> str:
        """The persona the chat's assistant answers with, as the caller's
        organisation has it. It is written onto the chat's assistant when the
        chat is opened or changed."""
        ...

    @property
    def audit(self) -> HelperChatAudit: ...

    @property
    def refusals(self) -> HelperChatRefusals: ...

    async def require_available(self, container: Container) -> None:
        """Refuse when the target's kind is not offered to the caller's
        tenant, before any chat is read. Opening and changing a chat, a turn
        and every tool call ask first."""
        ...

    def target_exists(self, tenant_id: UUID) -> sa.ColumnElement[bool]:
        """Whether the target of the enclosing query's ``helper_chats`` row
        exists in ``tenant_id`` and in the chat's space."""
        ...

    def scoped_request(self, space_id: UUID) -> Request:
        """The request the access checks of a bound chat run under: scoped to
        the chat's space and the target's tool server."""
        ...

    async def require_read(
        self, container: Container, request: Request, target_id: UUID
    ) -> RecordT:
        """The target as the access check read it, or a refusal when the
        caller may not read it."""
        ...

    async def require_edit(
        self, container: Container, request: Request, target_id: UUID
    ) -> RecordT:
        """The target, or a refusal when the caller may not edit it."""
        ...

    async def load(self, container: Container, target_id: UUID) -> RecordT: ...

    def space_id(self, record: RecordT) -> UUID: ...

    def name(self, record: RecordT) -> str:
        """The name the chat's assistant and conversations get."""
        ...

    async def lock(self, container: Container, target_id: UUID) -> bool:
        """Lock the target before its chat and assistant are written; whether
        it still exists."""
        ...

    def changeable(self, record: RecordT) -> bool:
        """Whether anything in the target may change right now."""
        ...

    def require_changeable(self, record: RecordT) -> None:
        """Refuse when nothing in the target may change right now."""
        ...

    def organisation_default_model_id(self, container: Container) -> UUID | None:
        """The organisation's default model for the target's chats."""
        ...

    async def build_tool_server(
        self, *, token: str, tenant_id: UUID, editing: bool
    ) -> MCPServer:
        """The tool server of one turn: every tool in edit mode, else those
        the chat may call without it. ``editing`` is the mode the turn runs
        in (``helper_chat_service.turn_in_edit_mode``)."""
        ...


def _flow_target() -> HelperChatTarget[Any]:
    # The composition point: the flow target lives with the flows, which
    # import this package, and is imported only once a flow's chat is used.
    from eneo.flows.application.flow_authoring_chat import FLOW_TARGET

    return FLOW_TARGET


def _assistant_target() -> HelperChatTarget[Any]:
    # Lives with the assistants, which import this package, as the flow's
    # lives with the flows.
    from eneo.assistants.application.assistant_helper_chat import ASSISTANT_TARGET

    return ASSISTANT_TARGET


_TARGETS: Mapping[HelperChatTargetType, Callable[[], HelperChatTarget[Any]]] = {
    HelperChatTargetType.FLOW: _flow_target,
    HelperChatTargetType.ASSISTANT: _assistant_target,
}


def target_for(target_type: str) -> HelperChatTarget[Any]:
    """The target of a binding row's ``target_type``."""
    return _TARGETS[HelperChatTargetType(target_type)]()
