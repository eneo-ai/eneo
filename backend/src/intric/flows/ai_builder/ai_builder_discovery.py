from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery_decision_engine import (
    apply_discovery_decision_engine,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    comparison_architecture_is_clear as _comparison_architecture_is_clear,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    decision_support_scope_is_vague as _decision_support_scope_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    document_cardinality_is_vague as _document_cardinality_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    document_kind_is_vague as _document_kind_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    final_pdf_type_is_vague as _final_pdf_type_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    has_same_run_comparison_contradiction as _has_same_run_comparison_contradiction,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    latest_pending_question_id as _latest_pending_question_id,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    looks_like_case_scope_is_vague as _looks_like_case_scope_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    looks_like_input_mode_is_vague as _looks_like_input_mode_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    looks_like_output_is_vague as _looks_like_output_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    mixed_input_architecture_is_vague as _mixed_input_architecture_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    needs_docx_mode_choice as _needs_docx_mode_choice,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    needs_pdf_generation_mode_choice as _needs_pdf_generation_mode_choice,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    question_category as _question_category,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    reader_and_style_is_vague as _reader_and_style_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    runtime_metadata_is_vague as _runtime_metadata_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    structured_analysis_need_is_vague as _structured_analysis_need_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    ultra_vague_output_choice_is_vague as _ultra_vague_output_choice_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryAnalysis,
    DiscoveryCandidate,
    DiscoveryIssue,
    DiscoveryLanguage,
    DiscoveryProfile,
    SemanticAdjudicationResult,
)
from intric.flows.ai_builder.ai_builder_discovery_priority import (
    sort_discovery_issues,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile as _build_discovery_profile,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    default_discovery_assumptions as _default_discovery_assumptions,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    semantic_answers as _semantic_answers,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    text_has_task_verbs as _text_has_task_verbs,
)
from intric.flows.ai_builder.ai_builder_discovery_questions import (
    comparison_scope_conflict_question,
    comparison_scope_question,
    decision_support_scope_question,
    document_kind_question,
    document_material_scope_question,
    docx_output_mode_question,
    final_output_mode_question,
    final_pdf_type_question,
    flow_input_architecture_question,
    input_material_mode_question,
    localized_text,
    output_reader_question,
    pdf_generation_mode_question,
    processing_scope_question,
    question_exposure_for_id,
    question_suggestion_for_id,
    runtime_metadata_fields_question,
    structured_analysis_need_question,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    canonical_question_id,
    has_explicit_structured_answer,
    question_is_already_resolved,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_signal_confidence import (
    has_low_confidence_signals,
    score_conversation_signals,
)
from intric.flows.domain.flow import Flow


def analyze_discovery(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    semantic_result: SemanticAdjudicationResult | None = None,
) -> DiscoveryAnalysis:
    profile = _build_discovery_profile(
        conversation,
        flow=flow,
        supplemental_answers=_semantic_answers(semantic_result),
    )
    text = profile.text
    answers = profile.answers
    raw_issues: list[DiscoveryIssue] = []

    output_vague = _looks_like_output_is_vague(profile)
    case_scope_vague = _looks_like_case_scope_is_vague(profile)
    input_mode_vague = _looks_like_input_mode_is_vague(profile)

    if _has_same_run_comparison_contradiction(text, answers):
        raw_issues.append(
            DiscoveryIssue(
                issue_id="comparison_scope_conflict",
                category="comparison",
                severity="blocking",
                message=(
                    localized_text(
                        profile.language,
                        "Användaren valde en fil per körning men vill också jämföra flera "
                        "dokument i samma körning. Jämförelsearkitekturen måste redas ut innan kraven kan sammanfattas.",
                        "The user chose one file per run but also wants comparison across multiple "
                        "documents in the same run. Resolve the comparison architecture before summarizing.",
                    )
                ),
                suggestion=comparison_scope_conflict_question(profile.language),
                question_level="blocking",
            )
        )

    if case_scope_vague:
        raw_issues.append(
            DiscoveryIssue(
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
        )

    if input_mode_vague and profile.document_like_input:
        raw_issues.append(
            DiscoveryIssue(
                issue_id="input_material_mode",
                category="input",
                severity="blocking",
                message=localized_text(
                    profile.language,
                    "Det är fortfarande oklart vilket material användaren ska lämna vid körning.",
                    "It is still unclear what kind of runtime material the user should provide.",
                ),
                suggestion=input_material_mode_question(profile.language),
                question_level="blocking",
            )
        )

    if _mixed_input_architecture_is_vague(
        profile,
        explicit_resolved=has_explicit_structured_answer(
            conversation,
            "flow_input_architecture",
        ),
    ):
        raw_issues.append(
            DiscoveryIssue(
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
        )

    if _document_kind_is_vague(profile):
        raw_issues.append(
            DiscoveryIssue(
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
        )

    if _document_cardinality_is_vague(profile):
        raw_issues.append(
            DiscoveryIssue(
                issue_id="document_material_scope",
                category="input",
                severity="blocking",
                message=localized_text(
                    profile.language,
                    "Det är fortfarande oklart om ett ärende normalt består av ett dokument eller ett dokumentpaket med flera filer.",
                    "It is still unclear whether one case normally contains one source document or a document package with several files.",
                ),
                suggestion=document_material_scope_question(profile.language),
                question_level="high_value",
            )
        )

    if profile.comparison_requested and not _comparison_architecture_is_clear(
        text, answers
    ):
        raw_issues.append(
            DiscoveryIssue(
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
        )

    if output_vague:
        raw_issues.append(
            DiscoveryIssue(
                issue_id="final_output_mode",
                category="output",
                severity="blocking",
                message=localized_text(
                    profile.language,
                    "Slutresultatet är fortfarande för vagt för att flödet ska kunna designas säkert.",
                    "The final output format is still too vague to design the flow confidently.",
                ),
                suggestion=final_output_mode_question(profile.language),
                question_level="blocking",
            )
        )
    elif _ultra_vague_output_choice_is_vague(profile):
        raw_issues.append(
            DiscoveryIssue(
                issue_id="final_output_mode",
                category="output",
                severity="blocking",
                message=localized_text(
                    profile.language,
                    "Det är fortfarande oklart vilket slutresultat flödet ska leverera.",
                    "The final output is still too vague to summarize safely.",
                ),
                suggestion=final_output_mode_question(profile.language),
                question_level="blocking",
            )
        )

    if _needs_docx_mode_choice(profile) and not has_explicit_structured_answer(
        conversation,
        "docx_output_mode",
    ):
        raw_issues.append(
            DiscoveryIssue(
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
        )

    if _needs_pdf_generation_mode_choice(
        profile
    ) and not has_explicit_structured_answer(
        conversation,
        "pdf_generation_mode",
    ):
        raw_issues.append(
            DiscoveryIssue(
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
        )

    if _reader_and_style_is_vague(profile):
        raw_issues.append(
            DiscoveryIssue(
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
        )

    if _decision_support_scope_is_vague(profile):
        raw_issues.append(
            DiscoveryIssue(
                issue_id="decision_support_scope",
                category="output",
                severity="blocking",
                message=localized_text(
                    profile.language,
                    "Det är fortfarande oklart hur omfattande beslutsunderlaget ska vara.",
                    "The level of detail in the final decision-support output is still unclear.",
                ),
                suggestion=decision_support_scope_question(profile.language),
                question_level="nice_to_have",
            )
        )

    if _final_pdf_type_is_vague(profile):
        raw_issues.append(
            DiscoveryIssue(
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
        )

    if (
        _structured_analysis_need_is_vague(profile)
        and question_exposure_for_id("structured_analysis_need") == "user_requirement"
    ):
        raw_issues.append(
            DiscoveryIssue(
                issue_id="structured_analysis_need",
                category="automation",
                severity="blocking",
                message=localized_text(
                    profile.language,
                    "Det är fortfarande oklart om flödet ska ta fram strukturerad analys som återanvänds i senare steg.",
                    "It is still unclear whether the flow should produce structured analysis that later steps can reuse.",
                ),
                suggestion=structured_analysis_need_question(profile.language),
                question_level="high_value",
            )
        )

    if _runtime_metadata_is_vague(profile):
        raw_issues.append(
            DiscoveryIssue(
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
        )

    mvs_met = _has_minimum_viable_specification(profile)

    # Confidence gating: when MVS met and no blocking issues, check for
    # low-confidence inferred signals that need clarification
    if mvs_met and not any(i.severity == "blocking" for i in raw_issues):
        scored = score_conversation_signals(conversation, freeform_text=text)
        if has_low_confidence_signals(scored) and len(profile.answers) < 3:
            low_signal = next(
                (s for s in reversed(scored) if s.confidence == "low"), None
            )
            if low_signal is not None:
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
        suppressed_candidates,
        candidates,
    ) = _apply_discovery_decision_engine(
        issues=_dedupe_issues(raw_issues),
        profile=profile,
        conversation=conversation,
        semantic_result=semantic_result,
    )
    assumptions.extend(
        _default_discovery_assumptions(
            profile=profile,
            selected_question_ids=selected_question_ids,
            existing_assumptions=assumptions,
        )
    )

    return DiscoveryAnalysis(
        issues=tuple(selected_issues),
        mvs_met=mvs_met,
        assumptions=tuple(dict.fromkeys(assumptions)),
        selected_question_ids=tuple(selected_question_ids),
        suppressed_candidates=tuple(suppressed_candidates),
        candidates=tuple(candidates),
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


def build_discovery_followup(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    analysis: DiscoveryAnalysis | None = None,
) -> tuple[DiscoveryIssue, dict[str, object], str] | None:
    profile = _build_discovery_profile(conversation, flow=flow)
    analysis = analysis or analyze_discovery(conversation, flow=flow)
    pending_question_id = _latest_pending_question_id(conversation)
    if pending_question_id is not None and not question_is_already_resolved(
        pending_question_id,
        conversation,
        flow=flow,
    ):
        suggestion = question_suggestion_for_id(
            pending_question_id,
            language=profile.language,
        )
        if suggestion is not None and suggestion.exposure == "user_requirement":
            issue = next(
                (
                    current_issue
                    for current_issue in analysis.issues
                    if current_issue.suggestion is not None
                    and current_issue.suggestion.question_id == pending_question_id
                ),
                DiscoveryIssue(
                    issue_id=f"pending_{pending_question_id}",
                    category=_question_category(pending_question_id),
                    severity="blocking",
                    message="",
                    suggestion=suggestion,
                ),
            )
            question_data = {
                "question_id": suggestion.question_id,
                "question": suggestion.question,
                "options": [
                    {
                        "id": option.id,
                        "label": option.label,
                        "description": option.description,
                        "value": option.value,
                    }
                    for option in suggestion.options
                ],
                "selection_mode": suggestion.selection_mode,
                "allow_custom": suggestion.allow_custom,
            }
            return (
                issue,
                question_data,
                build_discovery_followup_text(
                    issue,
                    profile.language,
                ),
            )

    issue = analysis.next_issue
    if issue is None or issue.suggestion is None:
        return None

    suggestion = issue.suggestion
    question_data: dict[str, object] = {
        "question_id": suggestion.question_id,
        "question": suggestion.question,
        "options": [
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "value": option.value,
            }
            for option in suggestion.options
        ],
        "selection_mode": suggestion.selection_mode,
        "allow_custom": suggestion.allow_custom,
    }
    return issue, question_data, build_discovery_followup_text(issue, profile.language)


def build_registry_question_followup(
    question_id: str,
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
) -> tuple[dict[str, object], str] | None:
    canonical_id = canonical_question_id(question_id)
    if question_is_already_resolved(canonical_id, conversation, flow=flow):
        return None

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
    question_data: dict[str, object] = {
        "question_id": suggestion.question_id,
        "question": suggestion.question,
        "options": [
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "value": option.value,
            }
            for option in suggestion.options
        ],
        "selection_mode": suggestion.selection_mode,
        "allow_custom": suggestion.allow_custom,
    }
    return question_data, assistant_text


def build_discovery_guidance(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    analysis: DiscoveryAnalysis | None = None,
) -> str | None:
    analysis = analysis or analyze_discovery(conversation, flow=flow)
    next_issue = analysis.next_issue
    if next_issue is None or next_issue.suggestion is None:
        return None

    suggestion = next_issue.suggestion
    lines = [
        "- Discovery protocol: there is still blocking ambiguity or a contradiction.",
        "- Ask exactly ONE structured question now. Do not call `confirm_requirements`, `create_flow`, or `edit_flow` yet.",
        f"- Highest-priority blocker: {next_issue.message}",
        f'- Use `question_id="{suggestion.question_id}"`.',
        f"- Ask this question: {suggestion.question}",
        "- Use these clickable options with stable ids and values:",
    ]
    for option in suggestion.options:
        lines.append(
            f'  - id="{option.id}", label="{option.label}", value="{option.value}", description="{option.description}"'
        )

    remaining = [issue.message for issue in analysis.blocking_issues[1:]]
    if remaining:
        lines.append(
            "- After the user answers, reevaluate these remaining blockers before summarizing:"
        )
        lines.extend(f"  - {issue}" for issue in remaining)

    lines.append(
        "- Keep looping until there are no blocking ambiguities or contradictions left."
    )
    return "\n".join(lines)


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
        # MVS not met but no blocking issues — free discovery handles this
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
    if issue.issue_id == "decision_support_scope":
        return localized_text(
            language,
            "Jag behöver förstå hur omfattande slutresultatet ska vara innan jag kan sammanfatta lösningen.",
            "I need to understand how extensive the final output should be before I can summarize the solution.",
        )
    if issue.issue_id == "final_pdf_type":
        return localized_text(
            language,
            "Jag behöver förstå vilken typ av slut-PDF användaren vill ha innan jag kan sammanfatta lösningen.",
            "I need to understand what kind of final PDF the user wants before I can summarize the solution.",
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
    has_input = (
        profile.document_like_input
        or profile.audio_like_input
        or "input_material_mode" in profile.answers
    )
    has_output = (
        profile.final_output_text_or_docx or "final_output_mode" in profile.answers
    )
    has_purpose = (
        profile.case_like_flow
        or profile.comparison_requested
        or _text_has_task_verbs(profile.text)
    )
    return sum([has_input, has_output, has_purpose]) >= 2


def _apply_discovery_decision_engine(
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
    return apply_discovery_decision_engine(
        issues=issues,
        profile=profile,
        conversation=conversation,
        semantic_result=semantic_result,
        text_has_task_verbs=_text_has_task_verbs(profile.text),
    )
