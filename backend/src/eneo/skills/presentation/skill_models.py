from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.main.models import PaginatedResponse
from eneo.skills.domain.skill import (
    MAX_SKILL_DESCRIPTION_LENGTH,
    MAX_SKILL_DISPLAY_NAME_LENGTH,
    MAX_SKILL_SLUG_LENGTH,
    SkillAdoptionDrift,
    SkillAdoptionResourceKind,
    SkillBindingSource,
    SkillPublicationState,
)


class SkillContentInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=MAX_SKILL_DISPLAY_NAME_LENGTH)
    description: str = Field(min_length=1, max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    instructions: str = Field(min_length=1)


class SkillCreateRequest(SkillContentInput):
    slug: str = Field(min_length=1, max_length=MAX_SKILL_SLUG_LENGTH)


class SkillRevisionCreateRequest(SkillContentInput):
    pass


class SkillPublishRequest(BaseModel):
    expected_revision_id: UUID


class SkillRevisionRestoreRequest(BaseModel):
    reviewed_current_revision_id: UUID


class SkillActiveUpdateRequest(BaseModel):
    is_active: bool


class SkillRevisionPublic(BaseModel):
    id: UUID
    skill_id: UUID
    revision_number: int
    display_name: str
    description: str
    instructions: str
    content_digest: str
    created_by_user_id: UUID
    created_at: datetime


class SkillRevisionSummaryPublic(BaseModel):
    id: UUID
    skill_id: UUID
    revision_number: int
    display_name: str
    created_at: datetime


class SkillRevisionRestorePublic(BaseModel):
    revision: SkillRevisionPublic
    created: bool
    restored_from_revision_id: UUID
    restored_from_revision_number: int


class SkillSparse(BaseModel):
    id: UUID
    space_id: UUID
    slug: str
    is_active: bool
    current_revision_id: UUID
    current_revision_number: int
    display_name: str
    description: str
    content_digest: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class SkillPublic(SkillSparse):
    current_revision: SkillRevisionPublic


class OrganizationSkillSummaryPublic(SkillSparse):
    published_revision_number: int | None
    first_published_at: datetime | None
    publication_state: SkillPublicationState


class OrganizationSkillPublic(OrganizationSkillSummaryPublic):
    current_revision: SkillRevisionPublic


class SkillAdoptionResourcePublic(BaseModel):
    kind: SkillAdoptionResourceKind
    resource_id: UUID
    name: str
    space_id: UUID
    space_name: str
    revision_id: UUID
    revision_number: int
    drift: SkillAdoptionDrift


class SkillAdoptionPersonalChatPublic(BaseModel):
    revision_id: UUID
    revision_number: int
    drift: SkillAdoptionDrift


class SkillAdoptionRevisionCountPublic(BaseModel):
    revision_id: UUID
    revision_number: int
    assistant_count: int
    app_count: int
    personal_chat_pinned: bool


class SkillAdoptionSummaryPublic(BaseModel):
    assistant_count: int
    app_count: int
    distinct_space_count: int
    behind_published_count: int
    personal_chat: SkillAdoptionPersonalChatPublic | None
    revision_counts: list[SkillAdoptionRevisionCountPublic]


class SkillAdoptionProjectionPagePublic(BaseModel):
    summary: SkillAdoptionSummaryPublic
    items: list[SkillAdoptionResourcePublic]
    limit: int
    next_cursor: str | None = None


class OrganizationSkillSummaryPagePublic(
    PaginatedResponse[OrganizationSkillSummaryPublic]
):
    limit: int
    next_cursor: str | None = None


class PublishedSkillSummaryPublic(BaseModel):
    id: UUID
    slug: str
    revision_id: UUID
    revision_number: int
    display_name: str
    description: str
    content_digest: str
    first_published_at: datetime


class PublishedSkillRevisionPublic(BaseModel):
    id: UUID
    skill_id: UUID
    revision_number: int
    display_name: str
    description: str
    instructions: str
    content_digest: str
    created_at: datetime


class PublishedSkillPublic(PublishedSkillSummaryPublic):
    revision: PublishedSkillRevisionPublic


class PublishedSkillSummaryPagePublic(PaginatedResponse[PublishedSkillSummaryPublic]):
    limit: int
    next_cursor: str | None = None


class SkillBindingReferenceInput(BaseModel):
    skill_id: UUID
    skill_revision_id: UUID


class SkillBindingSummary(BaseModel):
    skill_id: UUID
    skill_revision_id: UUID
    attachable_revision_id: UUID | None
    slug: str
    revision_number: int
    attachable_revision_number: int | None
    display_name: str
    description: str
    content_digest: str
    position: int
    is_active: bool
    source: SkillBindingSource
