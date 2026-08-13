from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eneo.actors.actors.space_actor import SpaceAccessFacts
from eneo.ai_models.completion_models.completion_model import ModelKwargs


# This response projection validates only fields published by Applications.
# Omitted aggregate-only state must not force full-domain or file hydration.
@dataclass(frozen=True, slots=True)
class AssistantApplicationsProjection:
    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    completion_model_kwargs: ModelKwargs
    logging_enabled: bool
    user_id: UUID
    published: bool
    description: str | None
    metadata_json: dict[str, object] | None
    icon_id: UUID | None
    completion_model_id: UUID | None
    insight_enabled: bool


@dataclass(frozen=True, slots=True)
class GroupChatApplicationsProjection:
    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    user_id: UUID
    published: bool
    metadata_json: dict[str, object] | None
    icon_id: UUID | None
    insight_enabled: bool


@dataclass(frozen=True, slots=True)
class AppApplicationsProjection:
    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None
    published: bool
    user_id: UUID
    icon_id: UUID | None


@dataclass(frozen=True, slots=True)
class ServiceApplicationsProjection:
    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    prompt: str
    completion_model_kwargs: ModelKwargs
    user_id: UUID


@dataclass(frozen=True, slots=True)
class SpaceApplicationsProjection:
    access: SpaceAccessFacts
    assistants: tuple[AssistantApplicationsProjection, ...]
    group_chats: tuple[GroupChatApplicationsProjection, ...]
    apps: tuple[AppApplicationsProjection, ...]
    services: tuple[ServiceApplicationsProjection, ...]
