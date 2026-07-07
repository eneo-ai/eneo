from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
        FlowCapabilityProfile,
    )
    from eneo.flows.ai_builder.ai_builder_edit_scope import EditScopeResolution
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.domain.flow import Flow

from eneo.flows.ai_builder.ai_builder_event_models import StructuredQuestionPayload
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    InputIntentResolution,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    DiscoveryFamily as DiscoveryFamily,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    DiscoveryImpact,
)
from eneo.flows.ai_builder.planning_state import PlanningState, ResolvedSlot
from eneo.flows.ai_builder.question_catalog import QuestionExposure

DiscoverySeverity = Literal["blocking", "info"]
DiscoveryLanguage = Literal["sv", "en"]
QuestionLevel = Literal["blocking", "high_value", "nice_to_have"]
DiscoveryConfidence = Literal["high", "medium", "low"]
DiscoveryResolvedBy = Literal[
    "structured_answer",
    "deterministic_inference",
    "llm_semantic_inference",
    "flow_default",
    "heuristic_assumption",
]
ReferenceSourceStatus = Literal[
    "not_requested",
    "missing",
    "same_run_sources",
    "existing_flow_or_knowledge",
    "unclear",
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


@dataclass(frozen=True, slots=True)
class ReferenceSourceResolution:
    status: ReferenceSourceStatus
    reason: str


@dataclass(frozen=True)
class DiscoveryAnalysis:
    issues: tuple[DiscoveryIssue, ...]
    mvs_met: bool = True
    selected_question_ids: tuple[str, ...] = ()

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
    reference_source: ReferenceSourceResolution
    document_like_input: bool
    case_like_flow: bool
    audio_like_input: bool
    final_output_text_or_docx: bool
    prefer_structured_intermediate: bool = False

    def resolved_slot(self, slot_name: str) -> ResolvedSlot | None:
        return self.planning_state.resolved_slots.get(slot_name)
