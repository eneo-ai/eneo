from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryCandidate,
    DiscoveryConfidence,
    DiscoveryImpact,
    DiscoveryIssue,
    DiscoveryProfile,
    DiscoveryResolvedBy,
    SemanticAdjudicationResult,
)
from intric.flows.ai_builder.ai_builder_discovery_priority import sort_discovery_issues
from intric.flows.ai_builder.ai_builder_discovery_questions import localized_text
from intric.flows.ai_builder.ai_builder_framework_policy import mentions_runtime_metadata
from intric.flows.ai_builder.ai_builder_signal_confidence import score_conversation_signals
from intric.flows.ai_builder.ai_builder_models import ConversationMessage

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

_QUESTION_FAMILY: dict[str, str] = {
    "comparison_scope_conflict": "case_scope",
    "case_scope": "case_scope",
    "comparison_scope": "case_scope",
    "input_material_mode": "input_shape",
    "flow_input_architecture": "input_shape",
    "document_kind": "input_shape",
    "document_material_scope": "input_shape",
    "final_output_mode": "output_artifact",
    "docx_output_mode": "output_artifact",
    "pdf_generation_mode": "output_artifact",
    "final_pdf_type": "output_style",
    "structured_analysis_need": "structured_reuse",
    "runtime_metadata_fields": "runtime_metadata",
    "output_reader": "output_style",
    "decision_support_scope": "output_style",
}


def apply_discovery_decision_engine(
    *,
    issues: list[DiscoveryIssue],
    profile: DiscoveryProfile,
    conversation: list[ConversationMessage],
    semantic_result: SemanticAdjudicationResult | None,
    text_has_task_verbs: bool,
) -> tuple[
    list[DiscoveryIssue],
    list[str],
    list[str],
    list[DiscoveryCandidate],
    list[DiscoveryCandidate],
]:
    scored_signals = score_conversation_signals(conversation, freeform_text=profile.text)
    rich_prompt = is_rich_prompt(profile, text_has_task_verbs=text_has_task_verbs)
    max_questions = 1 if has_explicit_step_plan(profile.text) else 2 if rich_prompt else 3
    assumptions: list[str] = list(semantic_result.assumptions if semantic_result else ())
    selected: list[DiscoveryIssue] = []
    selected_question_ids: list[str] = []
    suppressed: list[DiscoveryCandidate] = []
    candidates: list[DiscoveryCandidate] = []
    family_used: set[str] = set()

    for issue in issues:
        candidate = build_candidate(
            issue=issue,
            profile=profile,
            scored_signals=scored_signals,
            semantic_result=semantic_result,
        )
        candidates.append(candidate)
        question_id = candidate.question_id

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

        if len(selected_question_ids) >= max_questions and candidate.impact != "architecture":
            suppressed.append(
                suppressed_candidate(candidate, reason="question_budget_exhausted")
            )
            continue

        selected.append(issue)
        if question_id is not None:
            selected_question_ids.append(question_id)
        family_used.add(candidate.family)

    return (
        sort_discovery_issues(selected),
        assumptions,
        selected_question_ids,
        suppressed,
        candidates,
    )


def build_candidate(
    *,
    issue: DiscoveryIssue,
    profile: DiscoveryProfile,
    scored_signals,
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
        family=_QUESTION_FAMILY.get(issue.issue_id, issue.category),
        resolved_by=resolved_by,
        evidence=evidence,
    )


def candidate_confidence(
    *,
    issue_id: str,
    question_id: str | None,
    profile: DiscoveryProfile,
    scored_signals,
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
                return signal.confidence, "deterministic_inference", (
                    f"text signal: {signal.value}",
                )

    heuristic_reason = heuristic_confidence(issue_id, profile)
    if heuristic_reason is not None:
        return "medium", "heuristic_assumption", (heuristic_reason,)

    return "low", "deterministic_inference", ("no reliable inference",)


def heuristic_confidence(issue_id: str, profile: DiscoveryProfile) -> str | None:
    if issue_id == "case_scope" and implies_single_case(profile.text):
        return "singular case phrasing suggests one case per run"
    if issue_id == "document_material_scope" and implies_single_primary_document(profile.text):
        return "singular document phrasing suggests one primary document per run"
    if issue_id == "final_pdf_type" and implies_structured_report_pdf(profile.text):
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
    if candidate.issue_id == "document_material_scope" and implies_single_primary_document(profile.text):
        return localized_text(
            language,
            "Antar ett huvuddokument per körning tills du säger att ett dokumentpaket ska stödjas.",
            "Assuming one primary document per run unless you later say a document package must be supported.",
        )
    if candidate.issue_id == "final_pdf_type" and implies_structured_report_pdf(profile.text):
        return localized_text(
            language,
            "Antar att slut-PDF:n ska vara en strukturerad rapport snarare än en kort punktlista.",
            "Assuming the final PDF should be a structured report rather than a short bullet list.",
        )
    if candidate.issue_id == "document_kind" and looks_like_case_document_family(profile.text):
        return localized_text(
            language,
            "Antar att flödet främst ska arbeta med ärendeunderlag och andra kommunala handlingar.",
            "Assuming the flow primarily handles case material and related municipal documents.",
        )
    if candidate.issue_id == "structured_analysis_need" and explicit_structured_reuse_preference(profile.text):
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


def is_rich_prompt(
    profile: DiscoveryProfile,
    *,
    text_has_task_verbs: bool,
) -> bool:
    signal_count = 0
    if profile.document_like_input or profile.audio_like_input:
        signal_count += 1
    if profile.final_output_text_or_docx or "final_output_mode" in profile.answers:
        signal_count += 1
    if profile.case_like_flow or profile.comparison_requested or text_has_task_verbs:
        signal_count += 1
    if mentions_runtime_metadata(profile.text):
        signal_count += 1
    if explicit_structured_reuse_preference(profile.text):
        signal_count += 1
    return signal_count >= 4


def has_explicit_step_plan(text: str) -> bool:
    return mentions_any(
        text,
        (
            "steg 1",
            "steg 2",
            "step 1",
            "step 2",
            "tre steg",
            "three steps",
            "3-stegs",
            "3-step",
        ),
    )


def implies_single_case(text: str) -> bool:
    if mentions_any(text, ("flera ärenden", "multiple cases", "several cases", "compare")):
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
