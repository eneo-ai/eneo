"""Explicit Space settings writes; resource lists belong to read projections."""

from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID

from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose

Item = TypeVar("Item")


@dataclass(frozen=True, slots=True)
class LinkEdit(Generic[Item]):
    """An explicit edit of one of the space's link lists: its model or MCP
    server links (ids), or its MCP tool switches (tool id and on or off).

    ``selected`` replaces the stored entries among ``shown``, the ids the space
    listed when it was loaded for this request. A stored entry outside
    ``shown`` is one the space hides (the space factory leaves out deprecated
    models and capability servers, the space repository loads no disabled
    general MCP server, and lists neither a hidden server's tools nor a tool
    the instance admin switched off for all), so it stays: a save replaces only
    what the space showed.
    """

    selected: tuple[Item, ...]
    shown: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class SpaceUpdate:
    name: str | NotProvided = NOT_PROVIDED
    description: str | None | NotProvided = NOT_PROVIDED
    security_classification_id: UUID | None | NotProvided = NOT_PROVIDED
    data_retention_days: int | None | NotProvided = NOT_PROVIDED
    icon_id: UUID | None | NotProvided = NOT_PROVIDED
    completion_models: LinkEdit[UUID] | None = None
    embedding_models: LinkEdit[UUID] | None = None
    transcription_models: LinkEdit[UUID] | None = None
    transcription_service_ids: list[UUID] | None = None
    mcp_servers: LinkEdit[UUID] | None = None
    enabled_capabilities: list[CapabilityPurpose] | None = None
    minimum_security_level: int | None = None
    mcp_tools: LinkEdit[tuple[UUID, bool]] | None = None

    def scalar_values(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "name": self.name,
                "description": self.description,
                "security_classification_id": self.security_classification_id,
                "data_retention_days": self.data_retention_days,
                "icon_id": self.icon_id,
            }.items()
            if is_provided(value)
        }
