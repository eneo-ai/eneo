"""Typed PlanningState persisted in `builder_sessions.planning_state_jsonb`.

PlanningState replaces the turn-by-turn reconstruction of discovery
state and is the single source of truth for what the planner has
learned, decided, and committed to. Business logic consumes the typed
Pydantic model here — partial JSONB operators
(`jsonb_set`, `||`, path updates) are forbidden. Every mutation follows
load → validate → mutate-in-python → serialize-full-snapshot, so the
JSONB column never drifts out of Pydantic's typed world.

Three first-class version stamps travel on every persisted state:
`fcm_version` (the Flow Capability Manifest in force), a
`planner_contract_version` (the planner I/O schema in force), and
`builder_schema_version` (this Pydantic shape itself). The stale-session
policy compares stamps at load time. `pattern_registry_version` and
`question_catalog_version` are module-internal hygiene counters owned
by their respective modules and are NOT stamped here.

Mutability vs revalidation: models are mutable because full-snapshot
discipline mutates in Python before re-serializing. Direct attribute
reassignment is revalidated (`validate_assignment=True`). Container
mutations (list/dict edits that bypass the validator) can still
introduce drift, so the save path must call `validated_snapshot()`
before writing.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FCM_VERSION: int = 1
PLANNER_CONTRACT_VERSION: int = 1
BUILDER_SCHEMA_VERSION: int = 1
PLANNING_STATE_PAYLOAD_CAP_BYTES: int = 128 * 1024
ARCHITECTURE_HASH_HEX_LENGTH: int = 64

_ARCHITECTURE_HASH_RE = re.compile(rf"^[0-9a-f]{{{ARCHITECTURE_HASH_HEX_LENGTH}}}$")

PlanningPhase = Literal[
    "awaiting_input",
    "discovering",
    "ready_to_commit",
    "plan_proposed",
]

SignalConfidence = Literal["high", "medium", "low"]

SignalSource = Literal[
    "structured_answer",
    "freeform_text",
    "flow_default",
    "policy_default",
    "heuristic",
]

SlotSource = Literal[
    "structured_answer",
    "requirements_summary",
    "flow_default",
    "policy_default",
    "heuristic",
]

SlotConfidence = Literal["high", "medium"]

InvariantResult = Literal["pass", "fail", "warning"]

StepInputType = Literal["text", "json", "image", "audio", "document", "file", "any"]
StepOutputType = Literal["text", "json", "pdf", "docx"]
StepOutputMode = Literal[
    "pass_through",
    "http_post",
    "transcribe_only",
    "template_fill",
]
AggregationIntent = Literal["linear", "aggregate", "compare"]


class _PlanningModel(BaseModel):
    """Strict base for every persisted PlanningState model.

    `extra="forbid"` fails on unknown fields so JSONB drift is caught
    at load time. `validate_assignment=True` re-runs validators on
    direct attribute reassignment — container-level mutations (list
    appends, dict sets) are still the caller's responsibility; the
    save path must revalidate via `PlanningState.validated_snapshot`.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class EvidenceRef(_PlanningModel):
    conversation_message_ids: list[str] = Field(default_factory=list[str])
    attachment_digest_hashes: list[str] = Field(default_factory=list[str])
    raw_prompt_hash: str = ""


class PlanningSignal(_PlanningModel):
    question_id: str
    value: str
    confidence: SignalConfidence
    source: SignalSource
    provenance: list[str] = Field(default_factory=list[str])


class ResolvedSlot(_PlanningModel):
    name: str
    value: str
    source: SlotSource
    evidence: list[str] = Field(default_factory=list[str])
    confidence: SlotConfidence


class StepTriple(_PlanningModel):
    input_type: StepInputType
    output_type: StepOutputType
    output_mode: StepOutputMode


class ArchitectureCommitDraft(_PlanningModel):
    """Semantic architecture commitment.

    The model may choose the high-level `commit_architecture` action,
    but the server should derive this draft whenever possible. The
    tuple chain is a capability envelope from primary input to terminal
    output; it is not an exact implementation-step count. Deterministic
    mechanics (`architecture_hash`, `committed_at`) are server-owned
    and added only when the draft is finalized into a persisted
    `ArchitectureCommit`.
    """

    tuples_chain: list[StepTriple]
    chosen_patterns: list[str]
    required_capabilities: list[str] = Field(default_factory=list[str])
    aggregation_intent: AggregationIntent = "linear"

    @model_validator(mode="after")
    def _at_most_one_compiled_chain_pattern(self) -> "ArchitectureCommitDraft":
        from intric.flows.ai_builder.pattern_registry import (
            compiled_chain_pattern_ids,
        )

        compiled_pattern_ids = compiled_chain_pattern_ids(self.chosen_patterns)
        if len(compiled_pattern_ids) > 1:
            raise ValueError(
                "architecture_commit.chosen_patterns may include at most one "
                "compiler-backed chain pattern; got "
                f"{sorted(compiled_pattern_ids)}"
            )
        return self


class ArchitectureCommit(ArchitectureCommitDraft):
    """Persisted architecture commitment with server-owned metadata."""

    committed_at: datetime
    architecture_hash: str

    @field_validator("architecture_hash")
    @classmethod
    def _hash_is_64_hex(cls, value: str) -> str:
        if not _ARCHITECTURE_HASH_RE.fullmatch(value):
            raise ValueError(
                f"architecture_hash must be {ARCHITECTURE_HASH_HEX_LENGTH} "
                "lowercase hex characters (no prefix)"
            )
        return value


class OpenQuestion(_PlanningModel):
    question_id: str
    slot_name: str
    priority: int
    reason: str


class InvariantEvaluation(_PlanningModel):
    invariant_id: str
    result: InvariantResult
    detail: str = ""


class PlanningState(_PlanningModel):
    fcm_version: int
    planner_contract_version: int
    builder_schema_version: int
    phase: PlanningPhase
    evidence: EvidenceRef
    signals: list[PlanningSignal] = Field(default_factory=list[PlanningSignal])
    resolved_slots: dict[str, ResolvedSlot] = Field(
        default_factory=dict[str, ResolvedSlot]
    )
    architecture_commit: Optional[ArchitectureCommit] = None
    open_questions: list[OpenQuestion] = Field(default_factory=list[OpenQuestion])
    draft_plan_id: Optional[UUID] = None
    validation: list[InvariantEvaluation] = Field(
        default_factory=list[InvariantEvaluation]
    )

    @classmethod
    def empty(cls) -> PlanningState:
        """Fresh state for a new session — stamped at the current versions."""
        return cls(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
            phase="awaiting_input",
            evidence=EvidenceRef(),
        )

    def validated_snapshot(self) -> PlanningState:
        """Return a freshly revalidated copy suitable for the save path.

        Container-level mutations (list appends, dict inserts) bypass
        Pydantic's field validators. The save path calls this before
        writing so drift fails loudly instead of persisting.
        """
        return type(self).model_validate(self.model_dump(mode="json"))
