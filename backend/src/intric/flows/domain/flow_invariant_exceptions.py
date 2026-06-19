from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


class FlowInvariantError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FlowPersistedIdMissingError(FlowInvariantError):
    pass


@dataclass(frozen=True, slots=True)
class FlowPublishedDefinitionInvalidError(FlowInvariantError):
    flow_id: UUID
    flow_version: int
    parser_message: str
    parser_code: str | None
    parser_context: dict[str, object] | None = None

    def __str__(self) -> str:
        code = self.parser_code or "unclassified"
        return (
            "Publish built an invalid flow definition snapshot "
            f"(flow_id={self.flow_id}, flow_version={self.flow_version}, "
            f"parser_code={code}, parser_message={self.parser_message})."
        )
