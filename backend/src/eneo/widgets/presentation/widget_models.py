# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import date, datetime
from typing import Annotated, Any, Literal, Optional, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from eneo.audit.application.free_text import AuditedReason
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.oversight_models import (
    AdminSpaceAssistant,
    AdminSpaceKnowledgeSource,
    AdminSpaceViewerMembership,
    OversightClassification,
    OversightPersonRef,
    OversightRef,
)
from eneo.widgets.domain.widget import (
    MAX_DAILY_TOKEN_BUDGET,
    BotProtection,
    WidgetLanguage,
    WidgetLimits,
    WidgetPrivacy,
    WidgetStatus,
    WidgetTargetType,
    WidgetTexts,
    WidgetTheme,
    normalize_allowed_origins,
)
from eneo.widgets.domain.widget_template import TemplateLockGroup


class WidgetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: UUID = Field(description="Assistant in the space to publish.")
    name: str = Field(min_length=1, max_length=100)
    language: WidgetLanguage = WidgetLanguage.AUTO
    template_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Template the new widget follows: its texts, theme and language are"
            " copied now and its locked groups stay in step with the template."
        ),
    )


class WidgetLinkTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    revision: int = Field(ge=0)


class WidgetDetachTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)


class WidgetActivate(BaseModel):
    """Optional body of the activate command."""

    model_config = ConfigDict(extra="forbid")

    revision: int | SkipJsonSchema[None] = Field(
        default=None,
        ge=0,
        description=(
            "The revision that was reviewed. When set, activation is refused"
            " with `widget_revision_conflict` if the widget changed since."
        ),
    )


class WidgetActivationDecline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: AuditedReason = Field(
        description=(
            "What needs to change: at least 10 visible characters and at most"
            " 500 once invisible and control characters are removed, the text"
            " is NFC-composed and every whitespace run, line breaks included,"
            " is one space. Shown to the space's editors and stored in the"
            " audit log."
        )
    )


class WidgetTemplateLinkPublic(BaseModel):
    """The template a widget follows and which parts it governs."""

    id: UUID
    name: str
    locked_groups: list[TemplateLockGroup] = Field(
        description=(
            "Parts of the widget that follow the template and cannot be"
            " edited on the widget: appearance, language, legal_texts"
            " (disclosure and footer) and/or wording (title, welcome,"
            " placeholder)."
        )
    )


class WidgetConflictDetail(BaseModel):
    code: Literal["widget_revision_conflict"]
    message: str


class WidgetConflictResponse(BaseModel):
    detail: WidgetConflictDetail


class WidgetActivationRequestMissingDetail(BaseModel):
    code: Literal["widget_activation_request_missing"]
    message: str


class WidgetActivationRequestMissingResponse(BaseModel):
    detail: WidgetActivationRequestMissingDetail


class WidgetTemplateInUseDetail(BaseModel):
    code: Literal["template_in_use"]
    message: str


class WidgetTemplateInUseResponse(BaseModel):
    detail: WidgetTemplateInUseDetail


_WHOLE_GROUP = (
    "Replaces the whole group: a field left out of it takes its default, so"
    " send the current values along with the changed ones."
)


class WidgetUpdate(BaseModel):
    """Only the fields sent are changed; a field left out keeps its value.
    Null is refused: there is nothing to reset a field to."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)

    # None only marks a field left out; _no_nulls refuses a sent null, so the
    # schema does not offer one.
    name: Annotated[str, Field(min_length=1, max_length=100)] | SkipJsonSchema[None] = (
        None
    )
    texts: WidgetTexts | SkipJsonSchema[None] = Field(
        default=None, description=_WHOLE_GROUP
    )
    theme: WidgetTheme | SkipJsonSchema[None] = Field(
        default=None, description=_WHOLE_GROUP
    )
    limits: WidgetLimits | SkipJsonSchema[None] = Field(
        default=None, description=_WHOLE_GROUP
    )
    privacy: WidgetPrivacy | SkipJsonSchema[None] = Field(
        default=None, description=_WHOLE_GROUP
    )
    language: WidgetLanguage | SkipJsonSchema[None] = None
    allowed_origins: (
        Annotated[list[str], Field(max_length=20)] | SkipJsonSchema[None]
    ) = None
    bot_protection: BotProtection | SkipJsonSchema[None] = None
    show_sources: bool | SkipJsonSchema[None] = None
    show_tool_activity: bool | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def _no_nulls(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fields = cast(dict[object, object], data)
        nulls = sorted(str(key) for key, value in fields.items() if value is None)
        if nulls:
            raise ValueError(
                f"{', '.join(nulls)} cannot be null; leave a field out to"
                " keep its value."
            )
        return fields

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return None if value is None else normalize_allowed_origins(value)


class WidgetPublic(BaseModel):
    id: UUID
    public_id: str
    space_id: UUID
    target_type: WidgetTargetType
    target_id: UUID
    status: WidgetStatus
    token_generation: int
    revision: int
    name: str
    texts: WidgetTexts
    theme: WidgetTheme
    limits: WidgetLimits
    privacy: WidgetPrivacy
    language: WidgetLanguage
    allowed_origins: list[str]
    bot_protection: BotProtection
    show_sources: bool
    show_tool_activity: bool
    activation_blockers: list[str] = Field(
        description="Empty when the widget can be activated as configured."
    )
    template: Optional[WidgetTemplateLinkPublic] = Field(
        default=None,
        description="Set when the widget follows a template.",
    )
    created_by_user_id: Optional[UUID] = None
    activated_by_user_id: Optional[UUID] = None
    activated_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    activation_requested_at: Optional[datetime] = Field(
        default=None,
        description="Set while an editor's request for activation is pending.",
    )
    activation_requested_by_user_id: Optional[UUID] = None
    activation_declined_at: Optional[datetime] = Field(
        default=None,
        description="Set when an administrator sent the last request back.",
    )
    activation_declined_by_user_id: Optional[UUID] = None
    activation_decline_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WidgetTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    language: WidgetLanguage = WidgetLanguage.AUTO
    is_default: bool = False


class WidgetTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    texts: Optional[WidgetTexts] = None
    theme: Optional[WidgetTheme] = None
    language: Optional[WidgetLanguage] = None
    is_default: Optional[bool] = None
    locked_groups: Optional[list[TemplateLockGroup]] = Field(
        default=None,
        description=("Parts every follower is held to once this draft is published."),
    )


class WidgetTemplateReleasePublic(BaseModel):
    """A published release: what a widget receives when it links to the
    template and what its followers are held to."""

    texts: WidgetTexts
    theme: WidgetTheme
    language: WidgetLanguage
    locked_groups: list[TemplateLockGroup]


class WidgetTemplatePublic(BaseModel):
    """The draft (texts, theme, language, locked_groups) plus its publication
    state. Followers are linked to and locked by the published release."""

    id: UUID
    name: str
    description: str
    texts: WidgetTexts
    theme: WidgetTheme
    language: WidgetLanguage
    is_default: bool
    locked_groups: list[TemplateLockGroup]
    linked_widgets: int = Field(
        description="Widgets that follow this template right now."
    )
    published_at: Optional[datetime] = Field(
        default=None, description="None until the template is first published."
    )
    published_by_user_id: Optional[UUID] = None
    published: Optional[WidgetTemplateReleasePublic] = Field(
        default=None,
        description=(
            "The release widgets link to and are held to; the draft fields"
            " above may be ahead of it. None until the template is published."
        ),
    )
    has_unpublished_changes: bool = Field(
        description="The draft differs from the published release."
    )
    created_by_user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class WidgetOverviewItem(BaseModel):
    """One row of the admin overview: where a widget lives and how it is used."""

    id: UUID
    public_id: str
    name: str
    status: WidgetStatus
    space_id: UUID
    space_name: Optional[str] = None
    target_id: UUID
    assistant_name: Optional[str] = None
    allowed_origins: list[str]
    activated_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    updated_at: datetime
    questions_7d: int
    questions_30d: int
    input_tokens_30d: int
    output_tokens_30d: int
    blocked_30d: int
    helpful_30d: int = Field(
        description="Thumbs up on conversations started in the last 30 days."
    )
    unhelpful_30d: int = Field(
        description="Thumbs down on conversations started in the last 30 days."
    )
    last_activity: Optional[date] = None
    daily_token_budget: int = Field(
        description="The budget in force: the widget's, capped by the tenant policy."
    )
    budget_used_today: int = Field(
        description="Durable usage plus in-flight reservations for today's budget."
    )
    activation_blockers: list[str] = Field(
        default_factory=list,
        description=(
            "Why the widget could not be activated as configured: empty when"
            " it can. A policy violation does not stop an active widget: it is"
            " served within the policy."
        ),
    )
    activation_requested_at: Optional[datetime] = None
    activation_requested_by: Optional[OversightPersonRef] = Field(
        default=None,
        description="Who asked for activation; None when that user was deleted.",
    )


class WidgetOverviewTotals(BaseModel):
    widgets: int
    active: int
    awaiting_activation: int
    questions_7d: int
    questions_30d: int
    tokens_30d: int
    blocked_30d: int
    helpful_30d: int
    unhelpful_30d: int


class WidgetOverviewPublic(BaseModel):
    items: list[WidgetOverviewItem]
    totals: WidgetOverviewTotals


class AdminWidgetReviewTarget(BaseModel):
    assistant: AdminSpaceAssistant
    knowledge: list[AdminSpaceKnowledgeSource] = Field(
        description="The sources the assistant uses, with document counts."
    )
    visitor_mcp_servers: list[OversightRef] = Field(
        description="The assistant's general MCP servers that are switched on."
    )
    visitor_capabilities: list[Literal["web_search"]] = Field(
        description="Capabilities a visitor reaches; never image generation."
    )


class AdminWidgetReviewUsage(BaseModel):
    questions_7d: int
    questions_30d: int
    blocked_30d: int
    helpful_30d: int
    unhelpful_30d: int
    last_activity: Optional[date] = Field(
        default=None, description="The last day with visitor traffic."
    )


class AdminWidgetReview(BaseModel):
    """What an administrator reviews before a widget faces the public."""

    widget: WidgetPublic
    space: OversightRef
    space_kind: Literal["shared", "organization", "personal"]
    space_security_classification: Optional[OversightClassification] = None
    target: Optional[AdminWidgetReviewTarget] = Field(
        default=None,
        description=(
            "None for a personal space's assistant, or when the assistant no"
            " longer exists."
        ),
    )
    created_by: Optional[OversightPersonRef] = None
    activated_by: Optional[OversightPersonRef] = None
    activation_requested_by: Optional[OversightPersonRef] = None
    activation_declined_by: Optional[OversightPersonRef] = None
    viewer_role: Optional[SpaceRoleValue] = Field(
        default=None, description="Your effective role in the widget's space."
    )
    viewer_membership: Optional[AdminSpaceViewerMembership] = Field(
        default=None, description="Shared spaces only."
    )
    usage: AdminWidgetReviewUsage


class WidgetPreviewToken(BaseModel):
    """Visitor token for the admin page's live preview of the embed page."""

    token: str
    expires_in: int = Field(description="Seconds until the token expires.")
    public_id: str


class WidgetUsageDayPublic(BaseModel):
    day: date
    questions: int
    input_tokens: int
    output_tokens: int
    blocked_budget: int
    blocked_rate: int
    helpful: int = Field(description="Thumbs up on conversations started on the day.")
    unhelpful: int = Field(
        description="Thumbs down on conversations started on the day."
    )


class WidgetUsagePublic(BaseModel):
    days: list[WidgetUsageDayPublic]
    budget_used_today: int = Field(
        description="Tokens charged against today's budget, including reservations in flight."
    )
    daily_token_budget: int = Field(
        description="The budget in force: the widget's, capped by the tenant policy."
    )


class WidgetPolicyPublic(BaseModel):
    max_daily_token_budget: int
    allow_bot_protection_none: bool
    min_retention_days: int
    max_retention_days: int


class WidgetPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_daily_token_budget: Optional[int] = Field(
        default=None, ge=1_000, le=MAX_DAILY_TOKEN_BUDGET
    )
    allow_bot_protection_none: Optional[bool] = None
    min_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
    max_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
