from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eneo.main.models import NotProvided, PaginatedResponse
from eneo.skills.domain.skill import (
    MAX_SKILL_DESCRIPTION_LENGTH,
    MAX_SKILL_DISPLAY_NAME_LENGTH,
    MAX_SKILL_REMOVAL_BATCH_SIZE,
    MAX_SKILL_SLUG_LENGTH,
    AppPinAdvanceIncompatibleReason,
    AppPinAdvanceOutcome,
    AssistantPinAdvanceIncompatibleReason,
    AssistantPinAdvanceOutcome,
    PersonalChatPinAdvanceOutcome,
    SkillActivationFallbackReason,
    SkillActivationMode,
    SkillAdoptionDrift,
    SkillAdoptionResourceKind,
    SkillBindingSource,
    SkillPublicationState,
    SkillTurnEffectiveMode,
)
from eneo.tokens.token_utils import TokenCountSource


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


class PersonalChatPinAdvanceRequest(BaseModel):
    expected_pinned_revision_id: UUID = Field(
        description=(
            "The revision the Personal Chat binding was pinned to when the "
            "administrator reviewed the move."
        )
    )
    expected_published_revision_id: UUID = Field(
        description=(
            "The published revision the administrator reviewed as the "
            "target. A publish that lands after the review is refused as a "
            "conflict instead of silently applied."
        )
    )


class PersonalChatPinAdvancePublic(BaseModel):
    outcome: Literal[
        PersonalChatPinAdvanceOutcome.ADVANCED,
        PersonalChatPinAdvanceOutcome.ALREADY_CURRENT,
    ]
    from_revision_number: int
    to_revision_number: int


def _distinct_ids(value: list[UUID] | None) -> list[UUID] | None:
    if value is not None and len(value) != len(set(value)):
        raise ValueError("Select each resource once")
    return value


class AssistantFleetAdvanceRequest(BaseModel):
    expected_published_revision_id: UUID
    cursor: str | None = None
    assistant_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SKILL_REMOVAL_BATCH_SIZE,
        description=(
            "Restrict the update to these Assistants (one chunk, no cursor). "
            "Assistants already on the published revision are skipped."
        ),
    )

    @field_validator("assistant_ids")
    @classmethod
    def distinct_assistants(cls, value: list[UUID] | None) -> list[UUID] | None:
        return _distinct_ids(value)


class AssistantFleetAdvanceCountsPublic(BaseModel):
    advanced: int
    concurrent_change: int
    incompatible: int


class AssistantPinAdvanceOutcomePublic(BaseModel):
    assistant_id: UUID
    outcome: AssistantPinAdvanceOutcome
    reason: AssistantPinAdvanceIncompatibleReason | None = None


class AssistantFleetAdvancePublic(BaseModel):
    run_id: UUID
    next_cursor: str | None
    counts: AssistantFleetAdvanceCountsPublic
    outcomes: list[AssistantPinAdvanceOutcomePublic] = Field(max_length=100)


class AppFleetAdvanceRequest(BaseModel):
    expected_published_revision_id: UUID
    cursor: str | None = None
    app_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SKILL_REMOVAL_BATCH_SIZE,
        description=(
            "Restrict the update to these Apps (one chunk, no cursor). Apps "
            "already on the published revision are skipped."
        ),
    )

    @field_validator("app_ids")
    @classmethod
    def distinct_apps(cls, value: list[UUID] | None) -> list[UUID] | None:
        return _distinct_ids(value)


class AppFleetAdvanceCountsPublic(BaseModel):
    advanced: int
    concurrent_change: int
    incompatible: int


class AppPinAdvanceOutcomePublic(BaseModel):
    app_id: UUID
    outcome: AppPinAdvanceOutcome
    reason: AppPinAdvanceIncompatibleReason | None = None


class AppFleetAdvancePublic(BaseModel):
    run_id: UUID
    next_cursor: str | None
    counts: AppFleetAdvanceCountsPublic
    outcomes: list[AppPinAdvanceOutcomePublic] = Field(max_length=100)


class SkillRevisionRestoreRequest(BaseModel):
    reviewed_current_revision_id: UUID


class SkillActiveUpdateRequest(BaseModel):
    is_active: bool


class SkillRemovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_ids: list[UUID] = Field(min_length=1, max_length=MAX_SKILL_REMOVAL_BATCH_SIZE)
    detach_bindings: bool = Field(
        default=False,
        description=(
            "Also delete every Assistant, App and Personal Chat binding of the "
            "selected Skills in the same transaction. Without it, a bound Skill "
            "refuses the whole batch."
        ),
    )

    @field_validator("skill_ids")
    @classmethod
    def unique_skills(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Select distinct Skills")
        return value


class SkillBindingDetachRequest(BaseModel):
    """Assistants and Apps to detach one Skill from; at most 100 in total."""

    model_config = ConfigDict(extra="forbid")

    assistant_ids: list[UUID] = Field(default_factory=lambda: list[UUID]())
    app_ids: list[UUID] = Field(default_factory=lambda: list[UUID]())

    @field_validator("assistant_ids", "app_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Select each resource once")
        return value

    @model_validator(mode="after")
    def bounded_selection(self) -> "SkillBindingDetachRequest":
        total = len(self.assistant_ids) + len(self.app_ids)
        if not 1 <= total <= MAX_SKILL_REMOVAL_BATCH_SIZE:
            raise ValueError(
                f"Select between 1 and {MAX_SKILL_REMOVAL_BATCH_SIZE} resources"
            )
        return self


class SkillDetachmentTotalsPublic(BaseModel):
    """Distinct resources that lost a binding in one removal batch."""

    assistant_count: int
    app_count: int
    personal_chat_count: int = Field(
        description="Personal Chat policies that lost at least one selected Skill."
    )


class SkillRemovalPublic(BaseModel):
    removed_ids: list[UUID] = Field(
        description="Selected Skills confirmed removed, including previously removed Skills."
    )
    detached: SkillDetachmentTotalsPublic


class SkillUsageCountsPublic(BaseModel):
    assistant_count: int
    app_count: int
    distinct_space_count: int
    personal_chat_pinned: bool


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
    execution_blocked: bool
    removed_at: datetime | None
    usage: SkillUsageCountsPublic


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
    owner_name: str | None = Field(
        default=None, description="Owner of the personal space, when personal."
    )
    can_open: bool = Field(
        default=True,
        description="False for another user's personal space, which admins cannot open.",
    )


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
    summary: SkillAdoptionSummaryPublic | None
    items: list[SkillAdoptionResourcePublic]
    limit: int
    next_cursor: str | None = None
    matched_count: int | None = Field(
        default=None,
        description=(
            "Resources matching the filters across all pages; first page only."
        ),
    )


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
    execution_blocked: bool


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
    model_config = ConfigDict(extra="forbid")

    skill_id: UUID
    skill_revision_id: UUID


class AssistantSkillBindingInput(SkillBindingReferenceInput):
    activation_mode: SkillActivationMode | NotProvided = Field(
        default_factory=NotProvided
    )


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
    execution_blocked: bool


class AssistantSkillBindingSummary(SkillBindingSummary):
    activation_mode: SkillActivationMode


class AssistantSkillRuntimeSummary(BaseModel):
    effective_model_id: UUID
    effective_mode: SkillTurnEffectiveMode
    fallback_reason: SkillActivationFallbackReason | None
    skill_context_tokens: int
    skill_context_token_limit: int
    token_count_source: TokenCountSource


class AssistantSkillConfigurationPublic(BaseModel):
    bindings: list[AssistantSkillBindingSummary]
    runtime: AssistantSkillRuntimeSummary | None
