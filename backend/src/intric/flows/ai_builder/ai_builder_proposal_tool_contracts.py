"""Shared proposal tool contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ToolProcessingFailureKind,
)


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
class ToolRetryConfig:
    target_tool_name: str
    forced_tool_prompt: str
    process_tool_arguments: Callable[..., Awaitable[ToolProcessingResult]]
    process_tool_kwargs: dict[str, Any]
