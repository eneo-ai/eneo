from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    question_answer_from_metadata,
    question_answer_question_id,
)
from eneo.flows.ai_builder.ai_builder_discovery_families import (
    family_for_issue,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryCandidate,
    DiscoveryConfidence,
    DiscoveryIssue,
    DiscoveryProfile,
    DiscoveryResolvedBy,
)
from eneo.flows.ai_builder.ai_builder_discovery_priority import (
    DISCOVERY_ISSUE_PRIORITY,
)
from eneo.flows.ai_builder.ai_builder_discovery_questions import (
    localized_text,
    question_exposure_for_id,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    mentions_runtime_metadata,
)
from eneo.flows.ai_builder.ai_builder_signal_confidence import (
    ScoredSignal,
    score_conversation_signals,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import DiscoveryImpact
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
)

_NON_SLOT_QUESTION_IMPACT: dict[str, DiscoveryImpact] = {
    # Cross-slot contradiction gate; deciding wrong changes the flow shape.
    "comparison_scope_conflict": "architecture",
    # Legacy processing-scope question; quality guidance rather than topology.
    "case_scope": "quality",
    # Cross-input architecture conflict; deciding wrong changes the flow shape.
    "flow_input_architecture": "architecture",
    # Source-document kind refinement; improves reader quality.
    "document_kind": "quality",
    # Reference-source comparison gate; deciding wrong changes the flow shape.
    "comparison_scope": "architecture",
    # Reader/audience style refinement, so it stays non-blocking polish.
    "output_reader": "polish",
    # Output-scope style refinement, so it stays non-blocking polish.
    "final_output_scope": "polish",
    # PDF style refinement after terminal output is already known.
    "final_pdf_type": "quality",
}

_CATALOG_QUESTION_IMPACT: dict[str, DiscoveryImpact] = {
    template.id: template.impact for template in QUESTION_CATALOG.values()
}

_QUESTION_IMPACT: Mapping[str, DiscoveryImpact] = MappingProxyType(
    {
        **_NON_SLOT_QUESTION_IMPACT,
        **_CATALOG_QUESTION_IMPACT,
    }
)


def apply_discovery_decision_engine(
    *,
    issues: list[DiscoveryIssue],
    profile: DiscoveryProfile,
    conversation: list[ConversationMessage],
    slot_classification_result: SlotClassificationResult | None,
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
    max_questions = compute_question_budget(profile.text)
    spent_user_questions = _answered_user_requirement_question_count(conversation)
    assumptions: list[str] = list(
        slot_classification_result.assumptions if slot_classification_result else ()
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
            slot_classification_result=slot_classification_result,
        )
        question_id = candidate.question_id

        if (
            question_id is not None
            and question_exposure_for_id(question_id) != "user_requirement"
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
            spent_user_questions + len(selected_question_ids) >= max_questions
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


def _answered_user_requirement_question_count(
    conversation: list[ConversationMessage],
) -> int:
    question_ids: set[str] = set()
    for message in conversation:
        if message.role != "user":
            continue
        answer = question_answer_from_metadata(message.metadata)
        if answer is None:
            continue
        question_id = question_answer_question_id(answer)
        if question_id is None:
            continue
        if question_exposure_for_id(question_id) != "user_requirement":
            continue
        question_ids.add(question_id)
    return len(question_ids)


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
        issue.issue_id == "terminal_output"
        and profile.output_intent.terminal_output is None
        and profile.input_intent.primary_runtime_input != "unknown"
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
    slot_classification_result: SlotClassificationResult | None,
) -> DiscoveryCandidate:
    question_id = issue.suggestion.question_id if issue.suggestion is not None else None
    confidence, resolved_by, evidence = candidate_confidence(
        issue_id=issue.issue_id,
        question_id=question_id,
        profile=profile,
        scored_signals=scored_signals,
        slot_classification_result=slot_classification_result,
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
    slot_classification_result: SlotClassificationResult | None,
) -> tuple[DiscoveryConfidence, DiscoveryResolvedBy, tuple[str, ...]]:
    if slot_classification_result is not None and question_id is not None:
        classification_slot_name = question_id
        for slot in slot_classification_result.slots:
            if slot.slot_name != classification_slot_name:
                continue
            if slot.value == UNKNOWN_SLOT_VALUE:
                return "low", "llm_semantic_inference", (slot.reason,)
            return slot.confidence, "llm_semantic_inference", (slot.reason,)

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
        return "singular phrasing suggests one item per run"
    if issue_id == "document_material_scope" and implies_single_primary_document(
        profile.text
    ):
        return "singular document phrasing suggests one primary document per run"
    if (
        issue_id == "final_pdf_type"
        and profile.output_intent.terminal_output == "pdf_document"
        and implies_structured_report_pdf(profile.text)
    ):
        return "analytical-report phrasing suggests a structured report"
    if issue_id == "document_kind" and looks_like_case_document_family(profile.text):
        return "formal-document phrasing suggests reports and official material"
    return None


def candidate_assumption_safe(issue_id: str, profile: DiscoveryProfile) -> bool:
    if issue_id in {
        "comparison_scope_conflict",
        "primary_runtime_input",
        "flow_input_architecture",
        "comparison_scope",
        "structured_io_contract",
        "terminal_output",
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
    return True


def assumption_for_candidate(
    candidate: DiscoveryCandidate,
    profile: DiscoveryProfile,
) -> str | None:
    language = profile.language
    if candidate.issue_id == "case_scope" and implies_single_case(profile.text):
        return localized_text(
            language,
            "Antar en körning åt gången tills du säger att flera paket ska hanteras tillsammans.",
            "Assuming one run at a time unless you later say multiple packages should be handled together.",
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
            "Antar att flödet främst ska arbeta med rapporter, beslut och formella dokument.",
            "Assuming the flow primarily handles reports, decisions, and formal documents.",
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
    """Return the non-architecture question budget for this discovery pass.

    Architecture questions are allowed outside this budget. Quality and
    polish refinements should not keep advanced users in a loop once
    they have provided a detailed spec or explicitly told the builder to
    proceed with the plan.
    """
    normalized = text.casefold()
    if has_build_plan_intent(normalized) or is_detailed_flow_spec(normalized):
        return 0
    if has_explicit_step_plan(normalized):
        return 1
    return 3


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


def has_build_plan_intent(text: str) -> bool:
    return mentions_any(
        text.casefold(),
        (
            "bygg planen",
            "build the plan",
            "skapa planen",
            "create the plan",
            "det stämmer",
            "that is correct",
            "that looks right",
            "gå vidare",
            "go ahead",
            "fortsätt",
            "continue",
            "kör",
        ),
    )


def is_detailed_flow_spec(text: str) -> bool:
    word_count = len(text.split())
    if word_count >= 80:
        return True
    return word_count >= 35 and has_explicit_step_plan(text)


def implies_single_case(text: str) -> bool:
    if mentions_any(
        text, ("flera ärenden", "multiple cases", "several cases", "compare")
    ):
        return False
    return mentions_any(
        text,
        (
            "ett ärende",
            "ett kommunärende",
            "one case",
            "one municipal case",
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
            "risker",
            "möjligheter",
            "rekommendationer",
            "recommendations",
            "opportunities",
            "risks",
        ),
    )


def looks_like_case_document_family(text: str) -> bool:
    return mentions_any(
        text,
        (
            "underlag",
            "case material",
            "case files",
            "official material",
            "kommunärende",
            "municipal case",
            "tjänsteskrivelse",
            "remiss",
        ),
    )


def mentions_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
