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


class WidgetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: UUID = Field(description="Assistant in the space to publish.")
    name: str = Field(min_length=1, max_length=100)
    language: WidgetLanguage = WidgetLanguage.AUTO
    template_id: Optional[UUID] = Field(
        default=None,
        description="Template whose texts, theme and language are copied onto the new widget.",
    )


class WidgetApplyTemplate(BaseModel):
    template_id: UUID
    revision: int = Field(ge=0)


class WidgetConflictDetail(BaseModel):
    code: Literal["widget_revision_conflict"]
    message: str


class WidgetConflictResponse(BaseModel):
    detail: WidgetConflictDetail


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
    activation_blockers: list[str] = Field(
        description="Empty when the widget can be activated as configured."
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


class WidgetTemplatePublic(BaseModel):
    id: UUID
    name: str
    description: str
    texts: WidgetTexts
    theme: WidgetTheme
    language: WidgetLanguage
    is_default: bool
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
    last_activity: Optional[date] = None
    daily_token_budget: int
    budget_used_today: int = Field(
        description="Durable usage plus in-flight reservations for today's budget."
    )


class WidgetOverviewTotals(BaseModel):
    widgets: int
    active: int
    questions_7d: int
    questions_30d: int
    tokens_30d: int
    blocked_30d: int


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
