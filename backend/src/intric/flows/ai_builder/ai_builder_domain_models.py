"""Domain records for AI Flow Builder planning and materialization.

The portable Flow authoring graph lives in `intric.flows.flow_authoring_spec`.
This module owns AI Builder session, plan, and materialization records.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import uuid_utils
from pydantic import BaseModel, ConfigDict, Field

from intric.flows.ai_builder.ai_builder_edit_models import BuilderPlanEditResult
from intric.flows.domain.flow import FlowPersistedJsonObject
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
)


class SessionStatus(str, enum.Enum):
    CHATTING = "chatting"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    APPLIED = "applied"
    CANCELLED = "cancelled"


class PlanStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class TargetKind(str, enum.Enum):
    CREATE = "create"
    EDIT = "edit"


class LintSeverity(str, enum.Enum):
    WARNING = "warning"
    INFO = "info"


def _default_lint_warnings() -> list[LintWarning]:
    return []


def _default_conversation() -> list[ConversationMessage]:
    return []


class LintWarning(BaseModel):
    step_ref: str | None = None
    code: str
    message: str
    severity: LintSeverity = LintSeverity.WARNING


def _new_message_id() -> str:
    """UUIDv7 message id (time-sortable, stable across DB round-trips)."""
    return str(uuid_utils.uuid7())


class ConversationMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: str = Field(
        default_factory=_new_message_id,
        description=(
            "Stable id for this conversation turn. Used by evidence refs that "
            "must survive conversation compaction (positional indices do not)."
        ),
    )
    role: str
    content: str | None = None
    tool_call_id: str | None = Field(
        default=None,
        description="Planner-internal correlation id for a tool response turn.",
    )
    tool_calls: list[FlowPersistedJsonObject] | None = Field(
        default=None,
        description=(
            "Planner-internal tool trace metadata kept in the conversation history for debugging "
            "and replay. API consumers should not treat the exact tool trace shape as a stable "
            "business contract."
        ),
    )
    metadata: FlowPersistedJsonObject | None = None
    timestamp: datetime | None = None

    @classmethod
    def from_persisted(cls, data: Mapping[str, Any]) -> "ConversationMessage":
        """Hydrate a ConversationMessage from a DB/JSONB row.

        Refuses rows missing `message_id` — migration
        `20260421_builder_conv_msg_id` backfills every existing row. No
        rescue-logic: if we see a row without it post-migration, something
        is wrong and we want to fail loud instead of silently minting a
        fresh (and therefore not actually stable) id.
        """
        if "message_id" not in data:
            raise ValueError(
                "Persisted ConversationMessage is missing `message_id` — run "
                "alembic migration `20260421_builder_conv_msg_id` to backfill."
            )
        return cls.model_validate(data)


class BuilderSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    space_id: UUID
    actor_user_id: UUID | None = None
    target_kind: TargetKind
    flow_id: UUID | None = None
    latest_plan_id: UUID | None = None
    status: SessionStatus = SessionStatus.CHATTING
    conversation: list[ConversationMessage] = Field(
        default_factory=_default_conversation
    )
    requirements_version: str | None = None
    # Monotonic counter bumped by `save_planning_state`. Exposed on the
    # domain model so the JSON planner contract can echo it as
    # `base_planning_state_version` and the orchestrator's optimistic-
    # concurrency guard can reject stale deltas without a second repo
    # round-trip. Fresh rows default to 0 per the DB `server_default`.
    planning_state_version: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowBuilderProposalContent(BaseModel):
    """Typed proposal content reused by storage, HTTP responses, and SSE."""

    model_config = ConfigDict(extra="forbid")

    spec: FlowDraftSpecCore
    assumptions: list[str] = Field(default_factory=list)
    lint_warnings: list[LintWarning] = Field(default_factory=_default_lint_warnings)
    risk_acknowledgments: list[str] = Field(default_factory=list)
    plan_rationale: str | None = None
    edit_result: BuilderPlanEditResult | None = None


class FlowBuilderProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: FlowBuilderProposalContent
    reasoning: str | None = None
    resource_bindings: tuple[LocalResourceBinding, ...] = Field(default_factory=tuple)

    @property
    def spec(self) -> FlowDraftSpecCore:
        return self.content.spec

    @property
    def spec_hash(self) -> str:
        return self.spec.spec_hash()

    def storage_json(self) -> FlowPersistedJsonObject:
        return self.model_dump(mode="json", exclude_none=True, round_trip=True)

    @property
    def edit_result(self) -> BuilderPlanEditResult | None:
        return self.content.edit_result


class BuilderPlan(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    tenant_id: UUID
    status: PlanStatus = PlanStatus.PROPOSED
    proposal: FlowBuilderProposal
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def spec(self) -> FlowDraftSpecCore:
        return self.proposal.spec

    @property
    def spec_hash(self) -> str:
        return self.proposal.spec_hash

    @property
    def resource_bindings(self) -> tuple[LocalResourceBinding, ...]:
        return self.proposal.resource_bindings

    @property
    def edit_result(self) -> BuilderPlanEditResult | None:
        return self.proposal.edit_result


__all__ = [
    "BuilderPlan",
    "BuilderSession",
    "ConversationMessage",
    "FlowBuilderProposal",
    "FlowBuilderProposalContent",
    "LintSeverity",
    "LintWarning",
    "PlanStatus",
    "SessionStatus",
    "TargetKind",
]
