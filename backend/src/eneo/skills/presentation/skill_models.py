from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.skills.domain.skill import (
    MAX_SKILL_DESCRIPTION_LENGTH,
    MAX_SKILL_DISPLAY_NAME_LENGTH,
    MAX_SKILL_SLUG_LENGTH,
)


class SkillContentInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=MAX_SKILL_DISPLAY_NAME_LENGTH)
    description: str = Field(min_length=1, max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    instructions: str = Field(min_length=1)


class SkillCreateRequest(SkillContentInput):
    slug: str = Field(min_length=1, max_length=MAX_SKILL_SLUG_LENGTH)


class SkillRevisionCreateRequest(SkillContentInput):
    pass


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


class SkillBindingReferenceInput(BaseModel):
    skill_id: UUID
    skill_revision_id: UUID


class SkillBindingSummary(BaseModel):
    skill_id: UUID
    skill_revision_id: UUID
    current_revision_id: UUID
    slug: str
    revision_number: int
    current_revision_number: int
    display_name: str
    description: str
    content_digest: str
    position: int
    is_active: bool
