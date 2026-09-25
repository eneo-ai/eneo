# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""What tenant-admin oversight returns about a space.

Every field here is configuration or metadata; nothing is content. The
allowlist test (tests/unit/test_oversight_allowlist.py) freezes the field
paths, so a new field is always a deliberate decision.
"""

from datetime import date, datetime, timezone
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from eneo.audit.application.free_text import AuditedReason
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.domain import (
    K_ANONYMITY_THRESHOLD,
    USAGE_WINDOW_DAYS,
    ActivityBucket,
)
from eneo.widgets.domain.widget import WidgetStatus

AttentionReason = Literal["no_admin", "widget_activation_requested"]
KnowledgeKind = Literal["collection", "website", "integration"]
IntegrationType = Literal["sharepoint", "confluence", "onedrive"]
IntegrationItem = Literal["site", "folder", "file"]
UpdateInterval = Literal["never", "daily", "every_other_day", "weekly"]
MemberState = Literal["active", "invited", "inactive"]


def _utc_day(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    return value


# When a member last changed something, to the day: in a one-person space the
# time of day would show when that person worked.
ChangeDay = Annotated[date, BeforeValidator(_utc_day)]


class OversightRef(BaseModel):
    id: UUID
    name: str


class OversightPersonRef(BaseModel):
    id: UUID
    name: str = Field(description="The username, or the email when unset.")
    email: str


class OversightClassification(BaseModel):
    id: UUID
    name: str
    security_level: int


class OversightModelRef(BaseModel):
    id: UUID
    name: str = Field(description="The nickname, or the model name when unset.")
    hosting: Optional[str] = None
    org: Optional[str] = None


class AdminPrincipal(BaseModel):
    kind: Literal["user", "group"]
    id: UUID
    name: str


class AdminSpaceAdmins(BaseModel):
    manageable: bool = Field(
        description="At least one live, active or invited user holds the admin role."
    )
    count: int = Field(
        description="Distinct manageable admin users, direct or through a group."
    )
    principals: list[AdminPrincipal] = Field(
        description=(
            "Admin users who can manage the space, then admin groups with at"
            " least one such user."
        )
    )


class AdminSpaceMembershipSummary(BaseModel):
    role: Optional[SpaceRoleValue] = Field(
        default=None,
        description="Your effective role; None when you are not a member.",
    )
    via_group_only: bool
    oversight_joined_at: Optional[datetime] = None


class AdminSpaceViewerMembership(BaseModel):
    role: Optional[SpaceRoleValue] = None
    direct_role: Optional[SpaceRoleValue] = None
    group_role: Optional[SpaceRoleValue] = None
    via_groups: list[OversightRef] = Field(
        description="Your live groups that are members of the space."
    )
    oversight_joined_at: Optional[datetime] = None
    joinable_roles: list[SpaceRoleValue] = Field(
        description=(
            "Roles you may join with, lowest first: empty with a direct"
            " membership, otherwise the roles above your group role."
        )
    )
    can_leave: bool = Field(
        description=(
            "You have a direct membership and leaving keeps a manageable"
            " administrator in the space."
        )
    )


class AdminSpaceResourceCounts(BaseModel):
    assistants: int = Field(description="Excludes the space's default assistant.")
    apps: int
    group_chats: int
    knowledge_sources: int = Field(description="Sources the space owns.")


class AdminSpaceWidgetCounts(BaseModel):
    active: int
    paused: int
    draft: int
    awaiting_activation: int


class AdminSpaceListItem(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    icon_id: Optional[UUID] = None
    created_at: datetime
    security_classification: Optional[OversightClassification] = None
    member_count: int = Field(
        description="Distinct live users, directly or through live groups."
    )
    group_count: int
    admins: AdminSpaceAdmins
    resources: AdminSpaceResourceCounts
    widgets: AdminSpaceWidgetCounts
    last_activity: ActivityBucket
    viewer_membership: AdminSpaceMembershipSummary
    attention: list[AttentionReason]


class AdminWidgetRequestRef(BaseModel):
    widget_id: UUID
    widget_name: str
    space: OversightRef
    requested_at: datetime
    requested_by: Optional[OversightPersonRef] = Field(
        default=None, description="None when the user was deleted."
    )


class AdminSpaceList(BaseModel):
    items: list[AdminSpaceListItem]
    widget_requests: list[AdminWidgetRequestRef] = Field(
        description=(
            "Every pending widget activation request in the tenant, oldest"
            " first, the organisation space's included. Only the items of"
            " shared spaces count and flag them."
        )
    )


class AdminSpaceSettings(BaseModel):
    completion_models: list[OversightModelRef]
    embedding_models: list[OversightModelRef]
    transcription_models: list[OversightModelRef]
    mcp_servers: list[OversightRef]
    capabilities: list[CapabilityPurpose]
    data_retention_days: Optional[int] = None


_INTEGRATION_NAME = (
    "None for an integration source that is not a whole site: a file or"
    " folder name is a document title, and a OneDrive name is personal."
)
_INTEGRATION_ITEM = (
    "What an integration source covers: a whole site, a folder or a file."
)


class OversightKnowledgeRef(BaseModel):
    id: UUID
    name: Optional[str] = Field(default=None, description=_INTEGRATION_NAME)
    kind: KnowledgeKind
    integration_type: Optional[IntegrationType] = None
    integration_item: Optional[IntegrationItem] = Field(
        default=None, description=_INTEGRATION_ITEM
    )
    from_organization: bool


class AdminSpaceWidgetRef(BaseModel):
    id: UUID
    name: str
    status: WidgetStatus
    assistant: Optional[OversightRef] = None
    activation_requested_at: Optional[datetime] = None


class AdminSpaceAssistant(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    published: bool
    is_default: bool
    updated_at: ChangeDay = Field(description="The day (UTC) of the last change.")
    completion_model: Optional[OversightModelRef] = None
    instructions: Optional[str] = Field(
        default=None, description="The selected prompt."
    )
    knowledge_mode: Literal["tool", "inject"]
    knowledge: list[OversightKnowledgeRef]
    attachment_count: int
    mcp_servers: list[OversightRef]
    capabilities: list[CapabilityPurpose]
    insight_enabled: bool
    logging_enabled: bool
    data_retention_days: Optional[int] = Field(
        default=None,
        description="The assistant's own value; None follows the space.",
    )
    widgets: list[AdminSpaceWidgetRef] = Field(
        description=(
            "Every non-archived widget serving the assistant: active first,"
            " then paused, then drafts, each by name."
        ),
    )


class AdminSpaceApp(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    published: bool
    completion_model: Optional[OversightModelRef] = None
    transcription_model: Optional[OversightModelRef] = None
    instructions: Optional[str] = None
    data_retention_days: Optional[int] = None


class AdminSpaceGroupChat(BaseModel):
    id: UUID
    name: str
    published: bool
    insight_enabled: bool
    assistant_count: int


class AdminSpaceKnowledgeSource(BaseModel):
    id: UUID
    name: Optional[str] = Field(default=None, description=_INTEGRATION_NAME)
    kind: KnowledgeKind
    integration_type: Optional[IntegrationType] = None
    integration_item: Optional[IntegrationItem] = Field(
        default=None, description=_INTEGRATION_ITEM
    )
    item_count: int = Field(description="Active documents or pages.")
    size_bytes: int
    updated_at: Optional[ChangeDay] = Field(
        default=None,
        description=(
            "The day (UTC) the source last changed: an upload or removal, a"
            " crawl or a sync."
        ),
    )
    website_url: Optional[str] = None
    update_interval: Optional[UpdateInterval] = None
    requires_login: bool
    auto_disabled: bool = Field(description="Crawling stopped after repeated failures.")
    used_by: list[OversightRef] = Field(
        description="Assistants in the space that use the source."
    )


class AdminSpaceUsage(BaseModel):
    window_days: int = USAGE_WINDOW_DAYS
    threshold: int = K_ANONYMITY_THRESHOLD
    suppressed: bool = Field(
        description=(
            "At least one of questions, app runs and active users is withheld."
            " Each is judged on its own: it is shown only when at least"
            " `threshold` different signed-in people are behind it in the"
            " window."
        )
    )
    questions: Optional[int] = Field(
        default=None,
        description=(
            "Questions from signed-in users; None when fewer than `threshold`"
            " people asked."
        ),
    )
    app_runs: Optional[int] = Field(
        default=None,
        description="None when fewer than `threshold` people ran apps.",
    )
    active_users: Optional[int] = Field(
        default=None,
        description=(
            "People who asked questions or ran apps; None when fewer than `threshold`."
        ),
    )
    widget_questions: Optional[int] = Field(
        default=None,
        description=(
            "Questions through the space's web widgets that have been active"
            " at some point, including editors' and administrators' test"
            " questions. Questions to a widget that has never been active are"
            " not counted, and the value is None while no widget of the space"
            " has been: until then every question is a test by someone"
            " identifiable. Not held to `threshold`."
        ),
    )
    last_activity: ActivityBucket
    knowledge_bytes: int


class AdminSpaceOversightJoin(BaseModel):
    joined_at: datetime
    reason: str


class AdminSpaceUserMember(BaseModel):
    id: UUID
    username: Optional[str] = None
    email: str
    role: SpaceRoleValue
    state: MemberState
    is_tenant_admin: bool
    oversight_join: Optional[AdminSpaceOversightJoin] = None


class AdminSpaceGroupMember(BaseModel):
    id: UUID
    name: str
    role: SpaceRoleValue
    user_count: int = Field(description="Live users in the group.")


class AdminSpaceMembers(BaseModel):
    users: list[AdminSpaceUserMember] = Field(description="Admins first, then by name.")
    groups: list[AdminSpaceGroupMember]
    member_count: int
    group_count: int
    admins: AdminSpaceAdmins
    viewer_membership: AdminSpaceViewerMembership


class AdminSpaceDetail(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    icon_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    security_classification: Optional[OversightClassification] = None
    settings: AdminSpaceSettings
    usage: AdminSpaceUsage
    assistants: list[AdminSpaceAssistant] = Field(
        description="The default assistant is included and listed last."
    )
    apps: list[AdminSpaceApp]
    group_chats: list[AdminSpaceGroupChat]
    knowledge: list[AdminSpaceKnowledgeSource]
    inherited_knowledge_count: int = Field(
        description="Sources the space sees through the organisation space."
    )
    widgets: list[AdminSpaceWidgetRef] = Field(description="Non-archived widgets.")
    members: AdminSpaceMembers
    attention: list[AttentionReason]


class AdminSpaceMemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: SpaceRoleValue


class AdminSpaceGroupAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: UUID
    role: SpaceRoleValue


class AdminSpaceRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: SpaceRoleValue


class AdminSpaceJoin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: SpaceRoleValue
    reason: AuditedReason = Field(
        description=(
            "Why you need the content: at least 10 visible characters and at"
            " most 500 once invisible and control characters are removed, the"
            " text is NFC-composed and every whitespace run, line breaks"
            " included, is one space. Shown to the space's administrators and"
            " stored in the audit log."
        )
    )
