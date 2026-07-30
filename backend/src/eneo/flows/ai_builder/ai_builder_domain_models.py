"""Domain records for AI Flow Builder planning and materialization.

The portable Flow authoring graph lives in `eneo.flows.flow_authoring_spec`.
This module owns AI Builder session, plan, and materialization records.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Literal
from uuid import UUID

import uuid_utils
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer

from eneo.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    EditConfidence,
    FlowEditDiff,
)
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderPublicError
from eneo.flows.ai_builder.ai_builder_execution_shape import (
    FlowBuilderExecutionShape,
    build_flow_builder_execution_shape,
)
from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    FlowInputFieldProvenance,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
)

BUILDER_PROPOSAL_SCHEMA_VERSION: Literal[1] = 1
BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES: int = 1024 * 1024


class BuilderProposalPayloadTooLargeError(ValueError):
    """The serialized Builder proposal exceeds its persistence boundary."""

    def __init__(self, *, byte_size: int, cap_bytes: int) -> None:
        super().__init__(
            f"Builder proposal payload is {byte_size} bytes, over the "
            f"{cap_bytes}-byte cap."
        )
        self.byte_size = byte_size
        self.cap_bytes = cap_bytes


def _bounded_builder_proposal_json(
    payload: FlowPersistedJsonObject,
) -> bytes:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    byte_size = len(serialized)
    if byte_size > BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES:
        raise BuilderProposalPayloadTooLargeError(
            byte_size=byte_size,
            cap_bytes=BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES,
        )
    return serialized


class SessionStatus(str, enum.Enum):
    CHATTING = "chatting"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLIED = "applied"
    CANCELLED = "cancelled"


class BuilderTurnState(enum.StrEnum):
    OPEN = "open"
    PROCESSING = "processing"
    COMMITTED = "committed"
    FAILED_BEFORE_PROVIDER = "failed_before_provider"
    PROVIDER_OUTCOME_UNKNOWN = "provider_outcome_unknown"


class PlanStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    SUPERSEDED = "superseded"


class TargetKind(str, enum.Enum):
    CREATE = "create"
    EDIT = "edit"


class LintSeverity(str, enum.Enum):
    WARNING = "warning"
    INFO = "info"


def _default_lint_warnings() -> list[LintWarning]:
    return []


def _default_edit_advisories() -> list[EditAdvisory]:
    return []


def _default_conversation() -> list[ConversationMessage]:
    return []


class LintWarning(BaseModel):
    step_ref: str | None = None
    code: str
    message: str
    severity: LintSeverity = LintSeverity.WARNING
    field_name: str | None = None
    field_provenance: FlowInputFieldProvenance | None = None


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
    def from_persisted(cls, data: Mapping[str, object]) -> "ConversationMessage":
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


class BuilderTurnLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    client_turn_id: UUID
    request_fingerprint: str = Field(min_length=64, max_length=64)
    request: FlowPersistedJsonObject
    state: BuilderTurnState
    user_message_id: UUID
    error: AIBuilderPublicError | None = None


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
    # Monotonic counter bumped by `save_planning_state`. Exposed on the
    # domain model so the active turn can carry `base_planning_state_version`
    # through proposal submission and reject stale deltas without a second
    # repo round-trip. Fresh rows default to 0 per the DB `server_default`.
    planning_state_version: int = 0
    latest_turn: BuilderTurnLifecycle | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowBuilderEditApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_flow_revision: int
    removed_existing_step_refs: frozenset[str] = Field(default_factory=frozenset)
    diff: FlowEditDiff
    warnings: list[str] = Field(default_factory=list)
    advisories: list[EditAdvisory] = Field(default_factory=_default_edit_advisories)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: EditConfidence = "ready"

    @field_serializer("removed_existing_step_refs")
    def _serialize_removed_existing_step_refs(
        self, removed_existing_step_refs: frozenset[str]
    ) -> list[str]:
        return sorted(removed_existing_step_refs)


class FlowBuilderProposalContent(BaseModel):
    """Typed proposal content reused by storage, HTTP responses, and SSE."""

    model_config = ConfigDict(extra="forbid")

    spec: FlowDraftSpecCore
    assumptions: list[str] = Field(default_factory=list)
    lint_warnings: list[LintWarning] = Field(default_factory=_default_lint_warnings)
    plan_rationale: str | None = None
    description_override_manual: bool = False
    edit: FlowBuilderEditApproval | None = None

    @computed_field(repr=False)
    @property
    def execution_shape(self) -> FlowBuilderExecutionShape:
        return build_flow_builder_execution_shape(self.spec)


class FlowBuilderProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = BUILDER_PROPOSAL_SCHEMA_VERSION
    content: FlowBuilderProposalContent
    resource_bindings: tuple[LocalResourceBinding, ...] = Field(default_factory=tuple)

    @property
    def spec(self) -> FlowDraftSpecCore:
        return self.content.spec

    @property
    def spec_hash(self) -> str:
        return self.spec.spec_hash()

    @classmethod
    def from_persisted_json(
        cls,
        payload: Mapping[str, object],
    ) -> FlowBuilderProposal:
        schema_version = payload.get("schema_version")
        if schema_version is None:
            raise ValueError("Persisted builder proposal is missing schema_version.")
        if type(schema_version) is not int or schema_version != (
            BUILDER_PROPOSAL_SCHEMA_VERSION
        ):
            raise ValueError(
                f"Unsupported builder proposal schema_version: {schema_version!r}."
            )
        serialized = _bounded_builder_proposal_json(dict(payload))
        snapshot = cls.model_validate_json(serialized)
        canonical_payload = snapshot.model_dump(
            mode="json",
            exclude_none=True,
            round_trip=True,
        )
        # Authoring models normalize provider input; persisted snapshots must
        # already be canonical so hydration never hides stored corruption.
        if _bounded_builder_proposal_json(canonical_payload) != serialized:
            raise ValueError(
                "Persisted builder proposal is not canonical for schema_version "
                f"{BUILDER_PROPOSAL_SCHEMA_VERSION}."
            )
        return snapshot

    def storage_json(self) -> FlowPersistedJsonObject:
        # JSON-mode round-tripping forces mutated nested model instances back
        # through validation; a shallow Python validation would trust them.
        payload = self.model_dump(
            mode="json",
            exclude_none=True,
            round_trip=True,
            warnings=False,
        )
        snapshot = type(self).model_validate_json(
            _bounded_builder_proposal_json(payload)
        )
        validated_payload = snapshot.model_dump(
            mode="json",
            exclude_none=True,
            round_trip=True,
        )
        _bounded_builder_proposal_json(validated_payload)
        return validated_payload


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


__all__ = [
    "BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES",
    "BUILDER_PROPOSAL_SCHEMA_VERSION",
    "BuilderPlan",
    "BuilderProposalPayloadTooLargeError",
    "BuilderSession",
    "ConversationMessage",
    "FlowBuilderEditApproval",
    "FlowBuilderProposal",
    "FlowBuilderProposalContent",
    "LintSeverity",
    "LintWarning",
    "PlanStatus",
    "SessionStatus",
    "TargetKind",
]
