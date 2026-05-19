from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from intric.flows.flow_resource_bindings import LocalResourceKind


@dataclass(frozen=True, slots=True)
class AssistantAuthoringResourceRef:
    local_ref: str
    label: str | None = None
    local_kind: LocalResourceKind | None = None

    def __post_init__(self) -> None:
        normalized_ref = self.local_ref.strip()
        if not normalized_ref:
            raise ValueError("Assistant authoring resource ref must not be empty.")
        normalized_label = self.label.strip() if self.label else None
        object.__setattr__(self, "local_ref", normalized_ref)
        object.__setattr__(self, "label", normalized_label or None)

    @property
    def display_value(self) -> str:
        if self.label is None:
            return self.local_ref
        return f"{self.label} [{self.local_ref}]"


@dataclass(frozen=True, slots=True)
class AssistantAuthoringSnapshot:
    instructions: str
    model: AssistantAuthoringResourceRef | None = None
    knowledge_refs: tuple[AssistantAuthoringResourceRef, ...] = ()
    mcp_server_refs: tuple[AssistantAuthoringResourceRef, ...] = ()
    mcp_tool_refs: tuple[AssistantAuthoringResourceRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructions", self.instructions.strip())


AssistantAuthoringSnapshots = dict[UUID, AssistantAuthoringSnapshot]
