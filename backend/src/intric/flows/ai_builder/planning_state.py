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
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

FCM_VERSION: int = 1
PLANNER_CONTRACT_VERSION: int = 1
BUILDER_SCHEMA_VERSION: int = 1
PLANNING_STATE_PAYLOAD_CAP_BYTES: int = 128 * 1024

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


class _PlanningModel(BaseModel):
    """Strict base for every persisted PlanningState model.

    Unknown fields raise — the JSONB column must round-trip cleanly
    through the typed shape, so drift is caught at load time.
    """

    model_config = ConfigDict(extra="forbid")


class EvidenceRef(_PlanningModel):
    conversation_message_ids: list[str] = Field(default_factory=list)
    attachment_digest_hashes: list[str] = Field(default_factory=list)
    raw_prompt_hash: str = ""


class PlanningSignal(_PlanningModel):
    question_id: str
    value: str
    confidence: SignalConfidence
    source: SignalSource
    provenance: list[str] = Field(default_factory=list)


class ResolvedSlot(_PlanningModel):
    name: str
    value: str
    source: SlotSource
    evidence: list[str] = Field(default_factory=list)
    confidence: SlotConfidence


class ArchitectureCommit(_PlanningModel):
    tuples_chain: list[list[str]]
    chosen_patterns: list[str]
    committed_at: datetime
    architecture_hash: str


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
    builder_schema_version: int = BUILDER_SCHEMA_VERSION
    phase: PlanningPhase
    evidence: EvidenceRef
    signals: list[PlanningSignal] = Field(default_factory=list[PlanningSignal])
    resolved_slots: dict[str, ResolvedSlot] = Field(
        default_factory=dict[str, ResolvedSlot]
    )
    architecture_commit: Optional[ArchitectureCommit] = None
    open_questions: list[OpenQuestion] = Field(default_factory=list[OpenQuestion])
    draft_plan_id: Optional[int] = None
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
