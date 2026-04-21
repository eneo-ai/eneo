from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery_families import (
    family_for_issue,
)
from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryCandidate,
    DiscoveryConfidence,
    DiscoveryImpact,
    DiscoveryIssue,
    DiscoveryProfile,
    DiscoveryResolvedBy,
    SemanticAdjudicationResult,
)
from intric.flows.ai_builder.ai_builder_discovery_priority import (
    DISCOVERY_ISSUE_PRIORITY,
)
from intric.flows.ai_builder.ai_builder_discovery_questions import (
    localized_text,
    question_exposure_for_id,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    mentions_runtime_metadata,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    detect_planner_pattern_signals,
)
from intric.flows.ai_builder.ai_builder_signal_confidence import (
    ScoredSignal,
    score_conversation_signals,
)

_QUESTION_IMPACT: dict[str, DiscoveryImpact] = {
    "comparison_scope_conflict": "architecture",
    "case_scope": "quality",
    "input_material_mode": "architecture",
    "flow_input_architecture": "architecture",
    "document_kind": "quality",
    "document_material_scope": "quality",
    "comparison_scope": "architecture",
    "final_output_mode": "architecture",
    "docx_output_mode": "architecture",
    "pdf_generation_mode": "architecture",
    "output_reader": "polish",
    "decision_support_scope": "polish",
    "final_pdf_type": "quality",
    "structured_analysis_need": "quality",
    "runtime_metadata_fields": "quality",
}


def apply_discovery_decision_engine(
    *,
    issues: list[DiscoveryIssue],
    profile: DiscoveryProfile,
    conversation: list[ConversationMessage],
    semantic_result: SemanticAdjudicationResult | None,
) -> tuple[
    list[DiscoveryIssue],
    list[str],
    list[str],
    list[DiscoveryCandidate],
    list[DiscoveryCandidate],
]:
    scored_signals = score_conversation_signals(
        conversation, freeform_text=profile.text
    )
    planner_patterns = detect_planner_pattern_signals(profile.text)
    max_questions = compute_question_budget(profile.text)
    assumptions: list[str] = list(
        semantic_result.assumptions if semantic_result else ()
    )
    selected: list[DiscoveryIssue] = []
    selected_question_ids: list[str] = []
    suppressed: list[DiscoveryCandidate] = []
    candidates: list[DiscoveryCandidate] = []
    family_used: set[str] = set()

    for issue in _rank_issues_for_profile(issues, profile):
        candidate = build_candidate(
            issue=issue,
            profile=profile,
            scored_signals=scored_signals,
            semantic_result=semantic_result,
        )
        question_id = candidate.question_id

        if (
            question_id is not None
            and question_exposure_for_id(question_id) != "user_requirement"
            and not (
                question_id == "structured_analysis_need"
                and planner_patterns.rich_document_workflow
            )
        ):
            suppressed.append(
                suppressed_candidate(candidate, reason="planner_internal_question")
            )
            continue

        if (
            profile.edit_mode
            and candidate.family not in profile.edit_scope.active_families
        ):
            suppressed.append(
                suppressed_candidate(candidate, reason="inactive_edit_scope")
            )
            continue

        candidates.append(candidate)

        if candidate.impact == "polish":
            suppressed.append(
                suppressed_candidate(candidate, reason="polish_not_blocking")
            )
            continue

        assumption = assumption_for_candidate(candidate, profile)
        if candidate.assumption_safe and assumption is not None:
            assumptions.append(assumption)
            suppressed.append(
                suppressed_candidate(candidate, reason="assumed_from_context")
            )
            family_used.add(candidate.family)
            continue

        if candidate.family in family_used:
            suppressed.append(
                suppressed_candidate(candidate, reason="family_suppressed")
            )
            continue

        if candidate.confidence == "high" and assumption is not None:
            assumptions.append(assumption)
            suppressed.append(
                suppressed_candidate(candidate, reason="high_confidence_assumption")
            )
            family_used.add(candidate.family)
            continue

        if (
            len(selected_question_ids) >= max_questions
            and candidate.impact != "architecture"
        ):
            suppressed.append(
                suppressed_candidate(candidate, reason="question_budget_exhausted")
            )
            continue

        selected.append(issue)
        if question_id is not None:
            selected_question_ids.append(question_id)
        family_used.add(candidate.family)

    return (
        _rank_issues_for_profile(selected, profile),
        assumptions,
        selected_question_ids,
        suppressed,
        candidates,
    )


def _rank_issues_for_profile(
    issues: list[DiscoveryIssue],
    profile: DiscoveryProfile,
) -> list[DiscoveryIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            0 if issue.severity == "blocking" else 1,
            DISCOVERY_ISSUE_PRIORITY.get(issue.issue_id, 999)
            + _dynamic_issue_priority_offset(issue, profile),
        ),
    )


def _dynamic_issue_priority_offset(
    issue: DiscoveryIssue,
    profile: DiscoveryProfile,
) -> int:
    if issue.issue_id == "comparison_scope" and profile.comparison_requested:
        return -25
    if (
        issue.issue_id == "docx_output_mode"
        and profile.output_intent.terminal_output == "docx_document"
    ):
        return -20
    if (
        issue.issue_id == "pdf_generation_mode"
        and profile.output_intent.terminal_output == "pdf_document"
    ):
        return -20
    if (
        issue.issue_id == "final_output_mode"
        and profile.output_intent.terminal_output is None
        and not profile.case_like_flow
        and not profile.comparison_requested
        and len(profile.text.split()) <= 7
    ):
        return -20
    if issue.issue_id == "document_kind" and (
        profile.output_intent.terminal_output is not None
        or profile.comparison_requested
    ):
        return 20
    return 0


def build_candidate(
    *,
    issue: DiscoveryIssue,
    profile: DiscoveryProfile,
    scored_signals: list[ScoredSignal],
    semantic_result: SemanticAdjudicationResult | None,
) -> DiscoveryCandidate:
    question_id = issue.suggestion.question_id if issue.suggestion is not None else None
    confidence, resolved_by, evidence = candidate_confidence(
        issue_id=issue.issue_id,
        question_id=question_id,
        profile=profile,
        scored_signals=scored_signals,
        semantic_result=semantic_result,
    )
    return DiscoveryCandidate(
        issue_id=issue.issue_id,
        question_id=question_id,
        impact=_QUESTION_IMPACT.get(issue.issue_id, "quality"),
        confidence=confidence,
        assumption_safe=candidate_assumption_safe(issue.issue_id, profile),
        family=family_for_issue(issue.issue_id) or issue.category,
        resolved_by=resolved_by,
        evidence=evidence,
    )


def candidate_confidence(
    *,
    issue_id: str,
    question_id: str | None,
    profile: DiscoveryProfile,
    scored_signals: list[ScoredSignal],
    semantic_result: SemanticAdjudicationResult | None,
) -> tuple[DiscoveryConfidence, DiscoveryResolvedBy, tuple[str, ...]]:
    if semantic_result is not None and question_id is not None:
        for signal in semantic_result.signals:
            if signal.question_id != question_id:
                continue
            return signal.confidence, "llm_semantic_inference", (signal.reason,)

    if question_id is not None:
        for signal in scored_signals:
            if signal.question_id == question_id:
                return (
                    signal.confidence,
                    "deterministic_inference",
                    (f"text signal: {signal.value}",),
                )

    heuristic_reason = heuristic_confidence(issue_id, profile)
    if heuristic_reason is not None:
        return "medium", "heuristic_assumption", (heuristic_reason,)

    return "low", "deterministic_inference", ("no reliable inference",)


def heuristic_confidence(issue_id: str, profile: DiscoveryProfile) -> str | None:
    if issue_id == "case_scope" and implies_single_case(profile.text):
        return "singular case phrasing suggests one case per run"
    if issue_id == "document_material_scope" and implies_single_primary_document(
        profile.text
    ):
        return "singular document phrasing suggests one primary document per run"
    if (
        issue_id == "final_pdf_type"
        and profile.output_intent.terminal_output == "pdf_document"
        and implies_structured_report_pdf(profile.text)
    ):
        return "decision-support phrasing suggests a structured report"
    if issue_id == "document_kind" and looks_like_case_document_family(profile.text):
        return "case-analysis phrasing suggests case documents"
    return None


def candidate_assumption_safe(issue_id: str, profile: DiscoveryProfile) -> bool:
    if issue_id in {
        "comparison_scope_conflict",
        "input_material_mode",
        "flow_input_architecture",
        "comparison_scope",
        "final_output_mode",
        "docx_output_mode",
        "pdf_generation_mode",
    }:
        return False
    if issue_id == "case_scope":
        return implies_single_case(profile.text)
    if issue_id == "document_material_scope":
        return implies_single_primary_document(profile.text)
    if issue_id == "final_pdf_type":
        if profile.output_intent.terminal_output != "pdf_document":
            return False
        return implies_structured_report_pdf(profile.text)
    if issue_id == "document_kind":
        return looks_like_case_document_family(profile.text)
    if issue_id == "runtime_metadata_fields":
        return mentions_runtime_metadata(profile.text)
    if issue_id == "structured_analysis_need":
        return explicit_structured_reuse_preference(profile.text)
    return True


def assumption_for_candidate(
    candidate: DiscoveryCandidate,
    profile: DiscoveryProfile,
) -> str | None:
    language = profile.language
    if candidate.issue_id == "case_scope" and implies_single_case(profile.text):
        return localized_text(
            language,
            "Antar ett ärende åt gången per körning tills du säger att flera ärenden ska hanteras tillsammans.",
            "Assuming one case per run unless you later say multiple cases should be handled together.",
        )
    if (
        candidate.issue_id == "document_material_scope"
        and implies_single_primary_document(profile.text)
    ):
        return localized_text(
            language,
            "Antar ett huvuddokument per körning tills du säger att ett dokumentpaket ska stödjas.",
            "Assuming one primary document per run unless you later say a document package must be supported.",
        )
    if (
        candidate.issue_id == "final_pdf_type"
        and profile.output_intent.terminal_output == "pdf_document"
        and implies_structured_report_pdf(profile.text)
    ):
        return localized_text(
            language,
            "Antar att slut-PDF:n ska vara en strukturerad rapport snarare än en kort punktlista.",
            "Assuming the final PDF should be a structured report rather than a short bullet list.",
        )
    if candidate.issue_id == "document_kind" and looks_like_case_document_family(
        profile.text
    ):
        return localized_text(
            language,
            "Antar att flödet främst ska arbeta med ärendeunderlag och andra kommunala handlingar.",
            "Assuming the flow primarily handles case material and related municipal documents.",
        )
    if (
        candidate.issue_id == "structured_analysis_need"
        and explicit_structured_reuse_preference(profile.text)
    ):
        return localized_text(
            language,
            "Antar att strukturerad data ska användas i mellanliggande steg där det förbättrar kvalitet och återanvändning.",
            "Assuming structured data should be used in intermediate steps where it improves quality and reuse.",
        )
    return None


def suppressed_candidate(
    candidate: DiscoveryCandidate,
    *,
    reason: str,
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        issue_id=candidate.issue_id,
        question_id=candidate.question_id,
        impact=candidate.impact,
        confidence=candidate.confidence,
        assumption_safe=candidate.assumption_safe,
        family=candidate.family,
        resolved_by=candidate.resolved_by,
        evidence=candidate.evidence,
        selected=False,
        suppressed_reason=reason,
    )


def compute_question_budget(text: str) -> int:
    """Return 1 if user provided an explicit step plan, otherwise 3.

    Rich prompts should not receive fewer questions than short prompts (P0.2).
    """
    return 1 if has_explicit_step_plan(text) else 3


def has_explicit_step_plan(text: str) -> bool:
    return mentions_any(
        text.casefold(),
        (
            "steg 1",
            "steg 2",
            "steg 3",
            "step 1",
            "step 2",
            "step 3",
            "tre steg",
            "three steps",
            "3-stegs",
            "3-step",
            "fyra steg",
            "four steps",
            "4-stegs",
            "4-step",
        ),
    )


def implies_single_case(text: str) -> bool:
    if mentions_any(
        text, ("flera ärenden", "multiple cases", "several cases", "compare")
    ):
        return False
    return mentions_any(
        text,
        (
            "ett kommunärende",
            "ett ärende",
            "one municipal case",
            "one case",
            "ärendenummer",
            "case number",
        ),
    )


def implies_single_primary_document(text: str) -> bool:
    if mentions_any(
        text,
        (
            "flera dokument",
            "multiple documents",
            "several documents",
            "document package",
            "dokumentpaket",
        ),
    ):
        return False
    return mentions_any(
        text,
        (
            "underlag som pdf",
            "ett huvuddokument",
            "ett dokument",
            "en pdf",
            "one document",
            "one pdf",
            "uploaded pdf",
        ),
    )


def implies_structured_report_pdf(text: str) -> bool:
    return mentions_any(
        text,
        (
            "beslutsunderlag",
            "risker",
            "möjligheter",
            "rekommendationer",
            "decision support",
            "recommendations",
            "opportunities",
            "risks",
        ),
    )


def looks_like_case_document_family(text: str) -> bool:
    return mentions_any(
        text,
        (
            "kommunärende",
            "municipal case",
            "underlag",
            "case material",
            "beslutsunderlag",
            "tjänsteskrivelse",
            "remiss",
        ),
    )


def explicit_structured_reuse_preference(text: str) -> bool:
    return mentions_any(
        text,
        (
            "strukturerad data används där det förbättrar kvaliteten",
            "structured data where it improves quality",
            "structured analysis",
            "json",
            "output contract",
            "output_contract",
        ),
    )


def mentions_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
