from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
        FlowCapabilityProfile,
    )
    from intric.flows.ai_builder.ai_builder_edit_scope import EditScopeResolution
    from intric.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from intric.flows.domain.flow import Flow

from intric.flows.ai_builder.ai_builder_event_models import StructuredQuestionPayload
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    InputIntentResolution,
)
from intric.flows.ai_builder.planning_state import PlanningState, ResolvedSlot
from intric.flows.ai_builder.question_catalog import QuestionExposure

DiscoverySeverity = Literal["blocking", "info"]
DiscoveryLanguage = Literal["sv", "en"]
QuestionLevel = Literal["blocking", "high_value", "nice_to_have"]
DiscoveryImpact = Literal["architecture", "quality", "polish"]
DiscoveryConfidence = Literal["high", "medium", "low"]
DiscoveryResolvedBy = Literal[
    "structured_answer",
    "deterministic_inference",
    "llm_semantic_inference",
    "flow_default",
    "heuristic_assumption",
]
ClarificationAction = Literal["ask", "assume", "confirm", "plan"]
ClarificationReason = Literal[
    "model_slot_not_sufficient",
    "missing_architecture_requirement",
    "missing_outcome_requirement",
    "missing_reference_source",
    "missing_structured_payload_contract",
    "build_intent_and_sufficient",
    "all_blockers_resolved",
]


@dataclass(frozen=True)
class DiscoveryQuestionOption:
    id: str
    label: str
    description: str
    value: str


@dataclass(frozen=True)
class DiscoveryQuestionSuggestion:
    question_id: str
    question: str
    options: tuple[DiscoveryQuestionOption, ...]
    selection_mode: Literal["single", "multi"] = "single"
    allow_custom: bool = True
    exposure: QuestionExposure = "user_requirement"


@dataclass(frozen=True)
class DiscoveryIssue:
    issue_id: str
    category: str
    severity: DiscoverySeverity
    message: str
    suggestion: DiscoveryQuestionSuggestion | None = None
    question_level: QuestionLevel = "blocking"


@dataclass(frozen=True)
class BackendQuestion:
    question_data: StructuredQuestionPayload
    assistant_text: str
    issue: DiscoveryIssue | None = None


@dataclass(frozen=True)
class DiscoveryCandidate:
    issue_id: str
    question_id: str | None
    impact: DiscoveryImpact
    confidence: DiscoveryConfidence
    assumption_safe: bool
    family: str
    resolved_by: DiscoveryResolvedBy
    evidence: tuple[str, ...] = field(default_factory=tuple)
    selected: bool = False
    suppressed_reason: str | None = None


@dataclass(frozen=True)
class ClarificationDecisionTrace:
    mvs_met: bool
    selected_action: ClarificationAction
    selected_question_id: str | None
    selected_slot: str | None
    selected_reason: ClarificationReason
    selected_candidate: DiscoveryCandidate | None
    candidates: tuple[DiscoveryCandidate, ...]
    suppressed_candidates: tuple[DiscoveryCandidate, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryAnalysis:
    issues: tuple[DiscoveryIssue, ...]
    mvs_met: bool = True
    assumptions: tuple[str, ...] = ()
    selected_question_ids: tuple[str, ...] = ()
    suppressed_candidates: tuple[DiscoveryCandidate, ...] = ()
    candidates: tuple[DiscoveryCandidate, ...] = ()
    decision_trace: ClarificationDecisionTrace | None = None

    @property
    def blocking_issues(self) -> tuple[DiscoveryIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "blocking")

    @property
    def next_issue(self) -> DiscoveryIssue | None:
        return self.blocking_issues[0] if self.blocking_issues else None

    @property
    def ready_for_confirmation(self) -> bool:
        return self.mvs_met and not self.blocking_issues


@dataclass(frozen=True)
class DiscoveryProfile:
    language: DiscoveryLanguage
    text: str
    active_request_text: str
    answers: dict[str, set[str]]
    flow_defaults: dict[str, set[str]]
    capabilities: "FlowCapabilityProfile"
    edit_scope: "EditScopeResolution"
    input_intent: InputIntentResolution
    output_intent: "OutputIntentResolution"
    planning_state: PlanningState
    flow: Flow | None
    edit_mode: bool
    comparison_requested: bool
    document_like_input: bool
    case_like_flow: bool
    audio_like_input: bool
    final_output_text_or_docx: bool
    prefer_structured_intermediate: bool = False

    def resolved_slot(self, slot_name: str) -> ResolvedSlot | None:
        return self.planning_state.resolved_slots.get(slot_name)
