from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
        InputIntentResolution,
    )
    from intric.flows.domain.flow import Flow

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


@dataclass(frozen=True)
class DiscoveryIssue:
    issue_id: str
    category: str
    severity: DiscoverySeverity
    message: str
    suggestion: DiscoveryQuestionSuggestion | None = None
    question_level: QuestionLevel = "blocking"


@dataclass(frozen=True)
class SemanticAdjudicationSignal:
    question_id: str
    value: str
    confidence: DiscoveryConfidence
    reason: str


@dataclass(frozen=True)
class SemanticAdjudicationResult:
    signals: tuple[SemanticAdjudicationSignal, ...] = ()
    assumptions: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    cached: bool = False


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
class DiscoveryAnalysis:
    issues: tuple[DiscoveryIssue, ...]
    mvs_met: bool = True
    assumptions: tuple[str, ...] = ()
    selected_question_ids: tuple[str, ...] = ()
    suppressed_candidates: tuple[DiscoveryCandidate, ...] = ()
    candidates: tuple[DiscoveryCandidate, ...] = ()

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
    answers: dict[str, set[str]]
    flow_defaults: dict[str, set[str]]
    input_intent: InputIntentResolution
    flow: Flow | None
    edit_mode: bool
    comparison_requested: bool
    document_like_input: bool
    case_like_flow: bool
    audio_like_input: bool
    final_output_text_or_docx: bool
