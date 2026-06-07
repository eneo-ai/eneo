"""Declarative config capabilities — the contract shared by the chat plane
(loopback config-MCP) and, later, a schema-driven form plane.

A capability wraps one existing application-service operation with the metadata
both planes need: a Pydantic input model (the single source of truth for the MCP
tool schema AND a future generic form), a permission predicate, the handler that
calls the service, and audit metadata. The genericity lives here + in the shared
service layer, not in duplicated per-surface logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional
from uuid import UUID

from pydantic import BaseModel

if TYPE_CHECKING:
    from intric.actors.actors.space_actor import SpaceActor
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.main.container.container import Container
    from intric.spaces.space import Space
    from intric.users.user import UserInDB


class Scope(str, Enum):
    """Resource the edit-mode session is allowed to configure."""

    ASSISTANT = "assistant"
    SPACE = "space"
    TENANT = "tenant"


@dataclass
class CapabilityResult:
    """Outcome of running a capability handler."""

    summary: str
    entity_id: Optional[UUID] = None
    data: Optional[dict[str, Any]] = None


@dataclass
class CapabilityContext:
    """Per-request context handed to a capability handler.

    The container is bound to the authenticated user (via ``override_user``), so
    every service call the handler makes runs the normal ``SpaceActor`` checks.
    ``space`` is the assistant's space, already loaded; ``assistant_id`` is the
    edit-mode focus.
    """

    container: "Container"
    user: "UserInDB"
    space: "Space"
    assistant_id: UUID
    lang: str


@dataclass(frozen=True)
class ConfigCapability:
    id: str  # dotted id, e.g. "assistant.set_name"
    scope: Scope
    input_model: type[BaseModel]
    permission: Callable[["SpaceActor"], bool]
    handler: Callable[[CapabilityContext, BaseModel], Awaitable[CapabilityResult]]
    title_en: str
    description: str
    title_sv: str = ""
    mutating: bool = True
    confirm: bool = True
    audit_action: Optional["ActionType"] = None
    audit_entity: Optional["EntityType"] = None
    # Whether a generic schema-driven form may render this capability (phase 5).
    form_renderable: bool = False
    # Free-form confirmation summary template for the chat plane (localized).
    confirm_summary_en: str = ""
    confirm_summary_sv: str = ""

    def title(self, lang: str) -> str:
        if lang == "sv" and self.title_sv:
            return self.title_sv
        return self.title_en
