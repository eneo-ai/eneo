from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Final

from eneo.flows.ai_builder.ai_builder_discovery_decision_engine import (
    apply_discovery_decision_engine,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    EXTERNAL_DELIVERY_UNSUPPORTED_ISSUE_ID,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    document_cardinality_is_vague as _document_cardinality_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    document_kind_is_vague as _document_kind_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    external_delivery_requested as _external_delivery_requested,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    final_output_scope_is_vague as _final_output_scope_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    final_pdf_type_is_vague as _final_pdf_type_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    has_same_run_comparison_contradiction as _has_same_run_comparison_contradiction,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    looks_like_case_scope_is_vague as _looks_like_case_scope_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    mixed_input_architecture_is_vague as _mixed_input_architecture_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    needs_docx_mode_choice as _needs_docx_mode_choice,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    needs_pdf_generation_mode_choice as _needs_pdf_generation_mode_choice,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    post_processing_goal_is_vague as _post_processing_goal_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    primary_runtime_input_is_vague as _primary_runtime_input_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    question_category as _question_category,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    reader_and_style_is_vague as _reader_and_style_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    runtime_metadata_is_vague as _runtime_metadata_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    structured_io_contract_is_vague as _structured_io_contract_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    terminal_output_is_vague as _terminal_output_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    ultra_vague_terminal_output_choice_is_vague as _ultra_vague_terminal_output_choice_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    BackendQuestion,
    DiscoveryAnalysis,
    DiscoveryIssue,
    DiscoveryLanguage,
    DiscoveryProfile,
    DiscoveryQuestionSuggestion,
)
from eneo.flows.ai_builder.ai_builder_discovery_priority import (
    sort_discovery_issues,
)
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile as _build_discovery_profile,
)
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    expresses_task_intent as _expresses_task_intent,
)
from eneo.flows.ai_builder.ai_builder_discovery_questions import (
    comparison_scope_conflict_question,
    comparison_scope_question,
    document_kind_question,
    document_material_scope_question,
    docx_output_mode_question,
    external_delivery_internal_output_question,
    final_output_scope_question,
    final_pdf_type_question,
    flow_input_architecture_question,
    localized_text,
    output_reader_question,
    pdf_generation_mode_question,
    post_processing_goal_question,
    primary_runtime_input_question,
    processing_scope_question,
    question_suggestion_for_id,
    runtime_metadata_fields_question,
    structured_io_contract_question,
    terminal_output_question,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    canonical_question_id,
    has_explicit_structured_answer,
)
from eneo.flows.ai_builder.ai_builder_signal_confidence import (
    has_low_confidence_signals,
    score_conversation_signals,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.domain.flow import Flow

DiscoveryIssueBuilder = Callable[
    [list[ConversationMessage], DiscoveryProfile], DiscoveryIssue | None
]


def analyze_discovery(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    planning_state: PlanningState | None = None,
    slot_classification_result: SlotClassificationResult | None = None,
) -> DiscoveryAnalysis:
    profile = _build_discovery_profile(
        conversation,
        flow=flow,
        planning_state=planning_state,
    )
    mvs_met = _has_minimum_viable_specification(profile)
    raw_issues = _build_raw_discovery_issues(conversation, profile)
    if (
        planning_state is not None
        and planning_state.architecture_commit is not None
        and planning_state.mapped_file_limit.proposed_value is not None
        and planning_state.mapped_file_limit.accepted_value is None
    ):
        suggestion = question_suggestion_for_id(
            "mapped_file_limit", language=profile.language
        )
        if suggestion is not None:
            proposed_limit = planning_state.mapped_file_limit.proposed_value
            suggestion = replace(
                suggestion,
                options=tuple(
                    replace(
                        option,
                        label=localized_text(
                            profile.language,
                            f"Använd organisationens gräns ({proposed_limit})",
                            f"Use organization limit ({proposed_limit})",
                        ),
                    )
                    if option.id == "organization_limit"
                    else option
                    for option in suggestion.options
                ),
            )
            raw_issues.append(
                DiscoveryIssue(
                    issue_id="mapped_file_limit_confirmation_required",
                    category="input",
                    severity="blocking",
                    message=localized_text(
                        profile.language,
                        "Bekräfta filgränsen för mappad körning innan arkitekturen låses.",
                        "Confirm the mapped execution file limit before locking the architecture.",
                    ),
                    suggestion=suggestion,
                    question_level="blocking",
                )
            )

    # Confidence gating: when MVS met and no blocking issues, check for
    # low-confidence inferred signals that need clarification
    if mvs_met and not any(i.severity == "blocking" for i in raw_issues):
        scored = score_conversation_signals(conversation, freeform_text=profile.text)
        if has_low_confidence_signals(scored) and len(profile.answers) < 3:
            low_signal = next(
                (s for s in reversed(scored) if s.confidence == "low"), None
            )
            if low_signal is not None and not _classifier_resolved_question(
                question_id=low_signal.question_id,
                profile=profile,
                slot_classification_result=slot_classification_result,
            ):
                suggestion = question_suggestion_for_id(
                    low_signal.question_id, language=profile.language
                )
                if suggestion is not None and suggestion.exposure == "user_requirement":
                    raw_issues.append(
                        DiscoveryIssue(
                            issue_id=f"low_confidence_{low_signal.question_id}",
                            category=_question_category(low_signal.question_id),
                            severity="blocking",
                            message=localized_text(
                                profile.language,
                                f"Signalen för '{low_signal.question_id}' är osäker och behöver bekräftas.",
                                f"The signal for '{low_signal.question_id}' is ambiguous and needs confirmation.",
                            ),
                            suggestion=suggestion,
                            question_level="blocking",
                        )
                    )

    (
        selected_issues,
        assumptions,
        selected_question_ids,
    ) = _apply_discovery_decision_engine(
        issues=_dedupe_issues(raw_issues),
        profile=profile,
        conversation=conversation,
        slot_classification_result=slot_classification_result,
    )

    return DiscoveryAnalysis(
        issues=tuple(selected_issues),
        mvs_met=mvs_met,
        selected_question_ids=tuple(selected_question_ids),
        assumptions=tuple(assumptions),
    )


def _classifier_resolved_question(
    *,
    question_id: str,
    profile: DiscoveryProfile,
    slot_classification_result: SlotClassificationResult | None,
) -> bool:
    if slot_classification_result is None:
        return False
    canonical_id = canonical_question_id(question_id)
    classifier_slot = next(
        (
            slot
            for slot in slot_classification_result.slots
            if slot.slot_name == canonical_id
        ),
        None,
    )
    if (
        classifier_slot is None
        or classifier_slot.confidence == "low"
        or classifier_slot.value == UNKNOWN_SLOT_VALUE
    ):
        return False
    resolved_slot = profile.resolved_slot(canonical_id)
    return (
        resolved_slot is not None
        and classifier_slot.value == resolved_slot.value
        and resolved_slot.confidence != "low"
    )


def _build_raw_discovery_issues(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> list[DiscoveryIssue]:
    return [
        issue
        for builder in _DISCOVERY_ISSUE_BUILDERS
        if (issue := builder(conversation, profile)) is not None
    ]


def _build_comparison_scope_conflict_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _has_same_run_comparison_contradiction(profile.text, profile.answers):
        return None
    return DiscoveryIssue(
        issue_id="comparison_scope_conflict",
        category="comparison",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Användaren valde en fil per körning men vill också jämföra flera "
            "dokument i samma körning. Jämförelsearkitekturen måste redas ut innan kraven kan sammanfattas.",
            "The user chose one file per run but also wants comparison across multiple "
            "documents in the same run. Resolve the comparison architecture before summarizing.",
        ),
        suggestion=comparison_scope_conflict_question(profile.language),
        question_level="blocking",
    )


def _build_case_scope_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _looks_like_case_scope_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="case_scope",
        category="scope",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart vilket omfång varje körning ska ha.",
            "The flow scope per run is still unclear.",
        ),
        suggestion=processing_scope_question(profile.language),
        question_level="high_value",
    )


def _build_primary_runtime_input_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _primary_runtime_input_is_vague(profile):
        return None
    if not (profile.document_like_input or _expresses_task_intent(profile.text)):
        return None
    return DiscoveryIssue(
        issue_id="primary_runtime_input",
        category="input",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart vilket material användaren ska lämna vid körning.",
            "It is still unclear what kind of runtime material the user should provide.",
        ),
        suggestion=primary_runtime_input_question(profile.language),
        question_level="blocking",
    )


def _build_flow_input_architecture_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _mixed_input_architecture_is_vague(
        profile,
        explicit_resolved=has_explicit_structured_answer(
            conversation,
            "flow_input_architecture",
        ),
    ):
        return None
    return DiscoveryIssue(
        issue_id="flow_input_architecture",
        category="input",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Användaren verkar vilja kombinera ljudtranskribering och dokumentuppladdning i samma flöde, men inmatningsarkitekturen är inte löst ännu.",
            "The user appears to want both audio transcription and document upload in the same flow, but the input architecture is not resolved yet.",
        ),
        suggestion=flow_input_architecture_question(profile.language),
        question_level="blocking",
    )


def _build_document_kind_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _document_kind_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="document_kind",
        category="input",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart vilken typ av dokument flödet främst ska arbeta med.",
            "It is still unclear what kind of documents the flow should primarily handle.",
        ),
        suggestion=document_kind_question(profile.language),
        question_level="high_value",
    )


def _build_document_material_scope_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _document_cardinality_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="document_material_scope",
        category="input",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart om varje körning normalt består av ett dokument eller ett dokumentpaket med flera filer.",
            "It is still unclear whether one run normally contains one source document or a document package with several files.",
        ),
        suggestion=document_material_scope_question(profile.language),
        question_level="high_value",
    )


def _build_comparison_scope_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not profile.comparison_requested or profile.reference_source.status not in {
        "missing",
        "unclear",
    }:
        return None
    return DiscoveryIssue(
        issue_id="comparison_scope",
        category="comparison",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart hur jämförelsen mellan dokument ska fungera.",
            "The comparison architecture is unresolved.",
        ),
        suggestion=comparison_scope_question(profile.language),
        question_level="blocking",
    )


def _build_external_delivery_unsupported_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _external_delivery_requested(profile):
        return None
    if "terminal_output" in profile.answers:
        return None
    return DiscoveryIssue(
        issue_id=EXTERNAL_DELIVERY_UNSUPPORTED_ISSUE_ID,
        category="output",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Användaren vill skicka resultatet till ett externt API eller system, men AI Builder kan inte skapa ett utgående API-leveranssteg automatiskt i nya flöden ännu.",
            "The user wants to send the result to an external API or system, but AI Builder cannot automatically create an outbound API delivery step in new flows yet.",
        ),
        suggestion=external_delivery_internal_output_question(profile.language),
        question_level="blocking",
    )


def _build_structured_io_contract_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _structured_io_contract_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="structured_io_contract",
        category="outcome",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart hur input-JSON ska omvandlas till output-JSON.",
            "It is still unclear how input JSON should be transformed into output JSON.",
        ),
        suggestion=structured_io_contract_question(profile.language),
        question_level="blocking",
    )


def _build_post_processing_goal_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _post_processing_goal_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="post_processing_goal",
        category="outcome",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart vad flödet ska hjälpa användaren göra med materialet.",
            "It is still unclear what the flow should help the user do with the material.",
        ),
        suggestion=post_processing_goal_question(profile.language),
        question_level="high_value",
    )


def _build_terminal_output_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if _terminal_output_is_vague(profile):
        message = localized_text(
            profile.language,
            "Slutresultatet är fortfarande för vagt för att flödet ska kunna designas säkert.",
            "The final output format is still too vague to design the flow confidently.",
        )
    elif _ultra_vague_terminal_output_choice_is_vague(profile):
        message = localized_text(
            profile.language,
            "Det är fortfarande oklart vilket slutresultat flödet ska leverera.",
            "The final output is still too vague to summarize safely.",
        )
    else:
        return None
    return DiscoveryIssue(
        issue_id="terminal_output",
        category="output",
        severity="blocking",
        message=message,
        suggestion=terminal_output_question(profile.language),
        question_level="blocking",
    )


def _build_docx_output_mode_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _needs_docx_mode_choice(profile):
        return None
    if has_explicit_structured_answer(conversation, "docx_output_mode"):
        return None
    return DiscoveryIssue(
        issue_id="docx_output_mode",
        category="output",
        severity="blocking",
        message=localized_text(
            profile.language,
            "DOCX efterfrågas, men det är fortfarande oklart hur dokumentet ska skapas.",
            "DOCX output is requested, but the DOCX generation mode is unresolved.",
        ),
        suggestion=docx_output_mode_question(profile.language),
        question_level="blocking",
    )


def _build_pdf_generation_mode_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _needs_pdf_generation_mode_choice(profile):
        return None
    if has_explicit_structured_answer(conversation, "pdf_generation_mode"):
        return None
    return DiscoveryIssue(
        issue_id="pdf_generation_mode",
        category="output",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Användaren nämner PDF-mall, men det är fortfarande oklart om slutresultatet ska vara en vanlig genererad PDF eller om en fast mallförväntan måste hanteras uttryckligt.",
            "The user mentions a PDF template, but it is still unclear whether the result should be a normal generated PDF or whether a fixed template expectation must be handled explicitly.",
        ),
        suggestion=pdf_generation_mode_question(profile.language),
        question_level="blocking",
    )


def _build_output_reader_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _reader_and_style_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="output_reader",
        category="output",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart vem som främst ska läsa slutresultatet och vilken ton det bör ha.",
            "The main reader and tone of the final output are still unclear.",
        ),
        suggestion=output_reader_question(profile.language),
        question_level="nice_to_have",
    )


def _build_final_output_scope_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _final_output_scope_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="final_output_scope",
        category="output",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart hur detaljerat slutresultatet ska vara.",
            "The level of detail in the final output is still unclear.",
        ),
        suggestion=final_output_scope_question(profile.language),
        question_level="nice_to_have",
    )


def _build_final_pdf_type_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _final_pdf_type_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="final_pdf_type",
        category="output",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart vilken typ av PDF användaren vill ha som slutresultat.",
            "The style of the final PDF output is still unclear.",
        ),
        suggestion=final_pdf_type_question(profile.language),
        question_level="high_value",
    )


def _build_runtime_metadata_fields_issue(
    conversation: list[ConversationMessage],
    profile: DiscoveryProfile,
) -> DiscoveryIssue | None:
    if not _runtime_metadata_is_vague(profile):
        return None
    return DiscoveryIssue(
        issue_id="runtime_metadata_fields",
        category="input",
        severity="blocking",
        message=localized_text(
            profile.language,
            "Det är fortfarande oklart om användaren ska ange extra metadata vid körning.",
            "It is still unclear whether the user should provide extra runtime metadata.",
        ),
        suggestion=runtime_metadata_fields_question(profile.language),
        question_level="high_value",
    )


_DISCOVERY_ISSUE_BUILDERS: Final[tuple[DiscoveryIssueBuilder, ...]] = (
    _build_comparison_scope_conflict_issue,
    _build_case_scope_issue,
    _build_primary_runtime_input_issue,
    _build_flow_input_architecture_issue,
    _build_document_kind_issue,
    _build_document_material_scope_issue,
    _build_comparison_scope_issue,
    _build_external_delivery_unsupported_issue,
    _build_structured_io_contract_issue,
    _build_post_processing_goal_issue,
    _build_terminal_output_issue,
    _build_docx_output_mode_issue,
    _build_pdf_generation_mode_issue,
    _build_output_reader_issue,
    _build_final_output_scope_issue,
    _build_final_pdf_type_issue,
    _build_runtime_metadata_fields_issue,
)


def _dedupe_issues(issues: list[DiscoveryIssue]) -> list[DiscoveryIssue]:
    deduped: list[DiscoveryIssue] = []
    seen_question_ids: set[str] = set()
    seen_issue_ids: set[str] = set()
    for issue in issues:
        if issue.issue_id in seen_issue_ids:
            continue
        question_id = (
            issue.suggestion.question_id if issue.suggestion is not None else None
        )
        if question_id is not None and question_id in seen_question_ids:
            continue
        deduped.append(issue)
        seen_issue_ids.add(issue.issue_id)
        if question_id is not None:
            seen_question_ids.add(question_id)
    return sort_discovery_issues(deduped)


def build_registry_question_followup(
    question_id: str,
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
) -> BackendQuestion | None:
    canonical_id = canonical_question_id(question_id)
    profile = _build_discovery_profile(conversation, flow=flow)
    suggestion = question_suggestion_for_id(canonical_id, language=profile.language)
    if suggestion is None or suggestion.exposure != "user_requirement":
        return None

    issue = next(
        (
            issue
            for issue in analyze_discovery(conversation, flow=flow).issues
            if issue.suggestion is not None
            and issue.suggestion.question_id == canonical_id
        ),
        None,
    )
    assistant_text = build_discovery_followup_text(
        issue
        or DiscoveryIssue(
            issue_id=f"registry_{canonical_id}",
            category=_question_category(canonical_id),
            severity="blocking",
            message="",
            suggestion=suggestion,
        ),
        profile.language,
    )
    return BackendQuestion(
        question_data=_structured_question_payload_from_suggestion(suggestion),
        assistant_text=assistant_text,
        issue=issue,
    )


def _structured_question_payload_from_suggestion(
    suggestion: DiscoveryQuestionSuggestion,
) -> StructuredQuestionPayload:
    return StructuredQuestionPayload(
        question_id=suggestion.question_id,
        question=suggestion.question,
        options=[
            StructuredQuestionOptionPayload(
                id=option.id,
                label=option.label,
                description=option.description,
                value=option.value,
            )
            for option in suggestion.options
        ],
        selection_mode=suggestion.selection_mode,
        allow_custom=suggestion.allow_custom,
    )


def build_discovery_block_message(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    analysis: DiscoveryAnalysis | None = None,
) -> str | None:
    analysis = analysis or analyze_discovery(conversation, flow=flow)
    if analysis.ready_for_confirmation:
        return None
    issue = analysis.next_issue
    if issue is None:
        return None
    return issue.message


def build_discovery_followup_text(
    issue: DiscoveryIssue, language: DiscoveryLanguage
) -> str:
    if issue.issue_id == "comparison_scope_conflict":
        return localized_text(
            language,
            "Jag behöver reda ut en motsättning innan jag kan sammanfatta upplägget. Dina val pekar åt olika håll, så jag behöver ett förtydligande först.",
            "I need to resolve a contradiction before I can summarize the design. Your choices point in different directions, so I need one more clarification first.",
        )
    if issue.category == "comparison":
        return localized_text(
            language,
            "Jag behöver förstå hur jämförelsen ska fungera innan jag kan låsa arkitekturen.",
            "I need to understand how comparison should work before I can lock the architecture.",
        )
    if issue.category == "input":
        return localized_text(
            language,
            "Jag behöver förstå hur användaren ska lämna underlag vid körning innan jag går vidare.",
            "I need to understand how the user should provide material at runtime before I continue.",
        )
    if issue.issue_id == "output_reader":
        return localized_text(
            language,
            "Jag behöver förstå vem slutresultatet främst är till för innan jag kan sammanfatta lösningen.",
            "I need to understand who the final output is primarily for before I can summarize the solution.",
        )
    if issue.issue_id == "final_output_scope":
        return localized_text(
            language,
            "Jag behöver förstå hur detaljerat slutresultatet ska vara innan jag kan sammanfatta lösningen.",
            "I need to understand how detailed the final output should be before I can summarize the solution.",
        )
    if issue.issue_id == "final_pdf_type":
        return localized_text(
            language,
            "Jag behöver förstå vilken typ av slut-PDF användaren vill ha innan jag kan sammanfatta lösningen.",
            "I need to understand what kind of final PDF the user wants before I can summarize the solution.",
        )
    if issue.issue_id == "post_processing_goal":
        return localized_text(
            language,
            "Jag behöver förstå vad resultatet ska hjälpa dig göra innan jag kan bekräfta lösningen.",
            "I need to understand what the result should help you do before I can confirm the solution.",
        )
    if issue.issue_id == "structured_io_contract":
        return localized_text(
            language,
            "Jag behöver förstå JSON-kontraktet innan jag kan bekräfta lösningen.",
            "I need to understand the JSON contract before I can confirm the solution.",
        )
    if issue.issue_id == EXTERNAL_DELIVERY_UNSUPPORTED_ISSUE_ID:
        return localized_text(
            language,
            "AI Builder kan inte skapa ett utgående API-leveranssteg automatiskt ännu. Jag behöver därför välja vilket internt resultat flödet ska skapa för vidare hantering, till exempel JSON som kan användas av en integration eller ett konfigurerat HTTP POST-steg.",
            "AI Builder cannot automatically create an outbound API delivery step yet. I need to choose which internal result the flow should create for downstream handling, such as JSON that can be used by an integration or a configured HTTP POST step.",
        )
    if issue.issue_id == "pdf_generation_mode":
        return localized_text(
            language,
            "Jag behöver förstå om du menar en vanlig genererad PDF eller om du verkligen behöver en fast PDF-mall innan jag kan sammanfatta lösningen.",
            "I need to understand whether you mean a normal generated PDF or whether you truly need a fixed PDF template before I can summarize the solution.",
        )
    if issue.category == "output":
        return localized_text(
            language,
            "Jag behöver förstå slutresultatet lite bättre innan jag kan bekräfta lösningen.",
            "I need to understand the final output a bit better before I can confirm the solution.",
        )
    return localized_text(
        language,
        "Jag behöver reda ut en viktig detalj till innan jag kan sammanfatta kraven.",
        "I need to clarify one more important detail before I can summarize the requirements.",
    )


# ---------------------------------------------------------------------------
# MVS gate — Minimum Viable Specification
# ---------------------------------------------------------------------------


def _has_minimum_viable_specification(profile: DiscoveryProfile) -> bool:
    """Require at least 2 of 3 dimensions (input, output, purpose) resolved."""
    return (
        sum(
            [
                _has_mvs_input(profile),
                _has_mvs_output(profile),
                _has_mvs_purpose(profile),
            ]
        )
        >= 2
    )


def _has_mvs_input(profile: DiscoveryProfile) -> bool:
    return (
        profile.document_like_input
        or profile.audio_like_input
        or "primary_runtime_input" in profile.answers
    )


def _has_mvs_output(profile: DiscoveryProfile) -> bool:
    return profile.final_output_text_or_docx or "terminal_output" in profile.answers


def _has_mvs_purpose(profile: DiscoveryProfile) -> bool:
    return (
        profile.case_like_flow
        or profile.comparison_requested
        or _expresses_task_intent(profile.text)
    )


def _apply_discovery_decision_engine(
    *,
    issues: list[DiscoveryIssue],
    profile: DiscoveryProfile,
    conversation: list[ConversationMessage],
    slot_classification_result: SlotClassificationResult | None,
) -> tuple[
    list[DiscoveryIssue],
    list[str],
    list[str],
]:
    return apply_discovery_decision_engine(
        issues=issues,
        profile=profile,
        conversation=conversation,
        slot_classification_result=slot_classification_result,
    )
