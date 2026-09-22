# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.widgets.domain.widget import (
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


class WidgetTemplateInUseDetail(BaseModel):
    code: Literal["template_in_use"]
    message: str


class WidgetTemplateInUseResponse(BaseModel):
    detail: WidgetTemplateInUseDetail


class WidgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    texts: Optional[WidgetTexts] = None
    theme: Optional[WidgetTheme] = None
    limits: Optional[WidgetLimits] = None
    privacy: Optional[WidgetPrivacy] = None
    language: Optional[WidgetLanguage] = None
    allowed_origins: Optional[list[str]] = Field(default=None, max_length=20)
    bot_protection: Optional[BotProtection] = None
    show_sources: Optional[bool] = None
    tools_enabled: Optional[bool] = None

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
    tools_enabled: bool
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
        description="Net thumbs up registered in the last 30 days."
    )
    unhelpful_30d: int = Field(
        description="Net thumbs down registered in the last 30 days."
    )
    last_activity: Optional[date] = None
    daily_token_budget: int
    budget_used_today: int = Field(
        description="Durable usage plus in-flight reservations for today's budget."
    )
    activation_blockers: list[str] = Field(
        default_factory=list,
        description=(
            "Why the widget cannot be activated (or, for an active widget, why"
            " it is not serving): empty when it can."
        ),
    )


class WidgetOverviewTotals(BaseModel):
    widgets: int
    active: int
    questions_7d: int
    questions_30d: int
    tokens_30d: int
    blocked_30d: int
    helpful_30d: int
    unhelpful_30d: int


class WidgetOverviewPublic(BaseModel):
    items: list[WidgetOverviewItem]
    totals: WidgetOverviewTotals


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
    helpful: int = Field(description="Net thumbs up registered on the day.")
    unhelpful: int = Field(description="Net thumbs down registered on the day.")


class WidgetUsagePublic(BaseModel):
    days: list[WidgetUsageDayPublic]
    budget_used_today: int = Field(
        description="Tokens charged against today's budget, including reservations in flight."
    )
    daily_token_budget: int


class WidgetPolicyPublic(BaseModel):
    max_daily_token_budget: int
    allow_bot_protection_none: bool
    min_retention_days: int
    max_retention_days: int


class WidgetPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_daily_token_budget: Optional[int] = Field(default=None, ge=1_000)
    allow_bot_protection_none: Optional[bool] = None
    min_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
    max_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
