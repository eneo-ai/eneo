"""Shared proposal tool contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ToolProcessingFailureKind,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow


@dataclass(frozen=True)
class ToolProcessingResult:
    event: dict[str, str] | None = None
    events: tuple[dict[str, str], ...] = ()
    feedback: str | None = None
    failure_kind: ToolProcessingFailureKind | None = None
    failure_codes: frozenset[str] = frozenset()
    new_planning_state_version: int | None = None

    @property
    def has_events(self) -> bool:
        return self.event is not None or bool(self.events)

    def iter_events(self) -> tuple[dict[str, str], ...]:
        if self.event is None:
            return self.events
        return (self.event, *self.events)


@dataclass(frozen=True)
class ToolRetryInvocation:
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    arguments: dict[str, Any]
    assistant_content: str
    tool_call_id: str
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    resource_catalog: AIBuilderResourceCatalog | None = None
    flow: "Flow | None" = None
    assistant_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolRetryConfig:
    target_tool_name: str
    forced_tool_prompt: str
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[ToolProcessingResult]
    ]
