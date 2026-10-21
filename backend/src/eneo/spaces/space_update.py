"""Explicit Space settings writes; resource lists belong to read projections."""

from dataclasses import dataclass
from uuid import UUID

from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose


@dataclass(frozen=True, slots=True)
class SpaceUpdate:
    name: str | NotProvided = NOT_PROVIDED
    description: str | None | NotProvided = NOT_PROVIDED
    security_classification_id: UUID | None | NotProvided = NOT_PROVIDED
    data_retention_days: int | None | NotProvided = NOT_PROVIDED
    icon_id: UUID | None | NotProvided = NOT_PROVIDED
    completion_model_ids: list[UUID] | None = None
    embedding_model_ids: list[UUID] | None = None
    transcription_model_ids: list[UUID] | None = None
    mcp_server_ids: list[UUID] | None = None
    enabled_capabilities: list[CapabilityPurpose] | None = None
    minimum_security_level: int | None = None
    mcp_tools: list[tuple[UUID, bool]] | None = None

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
