# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.mcp_servers.domain.entities.mcp_server import MCP_TOOL_CATALOG_HARD_MAX_COUNT
from eneo.widgets.domain.widget import (
    MAX_DAILY_TOKEN_BUDGET,
    BotProtection,
    WidgetLanguage,
    WidgetLimits,
    WidgetPersona,
    WidgetPrivacy,
    WidgetStatus,
    WidgetTargetType,
    WidgetTexts,
    WidgetTheme,
)
from eneo.widgets.domain.widget import WidgetUpdate as WidgetUpdate
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


class WidgetExternalToolPublic(BaseModel):
    id: UUID
    name: str


class WidgetExternalToolServerPublic(BaseModel):
    """An MCP server outside Eneo that the widget's assistant reaches, with
    the tools the assistant has switched on there."""

    id: UUID
    name: str
    tools: list[WidgetExternalToolPublic]


class WidgetAcknowledgedServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tool_ids: list[UUID] = Field(max_length=MCP_TOOL_CATALOG_HARD_MAX_COUNT)


class WidgetExternalToolsAcknowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servers: list[WidgetAcknowledgedServer] = Field(
        description=(
            "The servers and tools the admin was shown, as `external_tools` on"
            " the widget lists them. Refused with `external_tools_changed`"
            " (listing the current `servers`) when they are not the current set."
        ),
    )


class WidgetExternalToolsChangedDetail(BaseModel):
    code: Literal["external_tools_changed"]
    message: str
    servers: list[WidgetExternalToolServerPublic]


class WidgetExternalToolsChangedResponse(BaseModel):
    detail: WidgetExternalToolsChangedDetail


class WidgetTemplateLinkPublic(BaseModel):
    """The template a widget follows and which parts it governs."""

    id: UUID
    name: str
    locked_groups: list[TemplateLockGroup] = Field(
        description=(
            "Parts of the widget that follow the template and cannot be"
            " edited on the widget: appearance, language, legal_texts"
            " (disclosure and footer), persona (name and avatar) and/or"
            " wording (title, welcome, placeholder)."
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
    persona: WidgetPersona
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
    external_tools: list[WidgetExternalToolServerPublic] = Field(
        description=(
            "The assistant's MCP servers outside Eneo and its tools there."
            " Visitor turns reach only the ones a tenant admin has acknowledged"
            " (`POST /widgets/{id}/acknowledge-external-tools/`), and activation"
            " needs all of them acknowledged."
        ),
    )
    external_tools_acknowledged: bool = Field(
        description=(
            "Whether the stored acknowledgement covers every tool in"
            " `external_tools`; true when there are none. False on an active"
            " widget means visitor turns run without the tools not covered."
        )
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
    persona: Optional[WidgetPersona] = None
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
    persona: WidgetPersona
    language: WidgetLanguage
    locked_groups: list[TemplateLockGroup]


class WidgetTemplatePublic(BaseModel):
    """The draft (texts, theme, persona, language, locked_groups) plus its
    publication state. Followers are linked to and locked by the published
    release."""

    id: UUID
    name: str
    description: str
    texts: WidgetTexts
    theme: WidgetTheme
    persona: WidgetPersona
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
    external_tools: list[str] = Field(
        description=(
            "Names of the assistant's MCP servers outside Eneo with a tool switched on."
        ),
    )
    external_tools_acknowledged: bool = Field(
        description=(
            "Whether the admin's acknowledgement covers every tool on the"
            " current `external_tools`; true when there are none."
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
    allow_external_tools: bool = Field(
        description=(
            "Whether widgets may publish assistants with tools switched on at MCP"
            " servers outside Eneo. Default true; off, such widgets cannot be"
            " activated, and live ones serve visitors without those tools and are"
            " flagged in the overview."
        )
    )


class WidgetPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_daily_token_budget: Optional[int] = Field(
        default=None, ge=1_000, le=MAX_DAILY_TOKEN_BUDGET
    )
    allow_bot_protection_none: Optional[bool] = None
    min_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
    max_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
    allow_external_tools: Optional[bool] = None
