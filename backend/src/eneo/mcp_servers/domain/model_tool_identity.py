from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ModelToolIdentity:
    """The exact model-visible name registered for one approved protocol tool."""

    model_name: str
    server_id: UUID
    tool_name: str
    purpose: str | None
