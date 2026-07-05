from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    ui_language_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_decision_engine import (
    implies_single_case,
    implies_single_primary_document,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_capability_profile,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryLanguage,
    DiscoveryProfile,
    ReferenceSourceResolution,
)
from eneo.flows.ai_builder.ai_builder_discovery_questions import localized_text
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_token_prefix,
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_edit_scope import (
    build_active_request_window,
    resolve_edit_scope,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    OutputIntentResolution,
    aggregate_freeform_user_text,
    extract_answer_signals,
    has_explicit_structured_answer,
    resolve_output_intent,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    InputIntentResolution,
    resolve_input_intent,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from eneo.flows.domain.flow import Flow

_PROFILE_ANSWER_SOURCES: frozenset[str] = frozenset(
    {
        "flow_default",
        "model",
        "policy_default",
        "requirements_summary",
        "structured_answer",
    }
)
_ACTIVE_REQUEST_ANSWER_SOURCES: frozenset[str] = frozenset(
    {
        "model",
        "requirements_summary",
        "structured_answer",
    }
)

_TASK_VERB_PREFIXES_SV = (
    # Prefixes are intentional: Swedish/English user requests are often
    # inflected, compounded, or phrased as "*-flöde" / "* flow"; matching is
    # token-prefix based so unrelated substrings do not become workflow intent.
    "sammanfatt",
    "analyser",
    "extraher",
    "transkrib",
    "jämför",
    "jämförelse",
    "jamfor",
    "jamforelse",
    "gransk",
    "generer",
    "bedom",
    "bedöm",
    "produc",
    "klassificer",
    "ocr",
)
_TASK_VERB_PREFIXES_EN = (
    "summar",
    "analy",
    "extract",
    "transcrib",
    "compar",
    "review",
    "generat",
    "assess",
    "produc",
    "triage",
    "classif",
    "categorize",
    "draft",
    "ocr",
)
_TASK_VERB_EXACT_TOKENS = (
    "skriv",
    "write",
)

_QUESTION_ACTION_MARKERS = (
    "add",
    "build",
    "bygg",
    "create",
    "gör",
    "gor",
    "i want",
    "jag vill",
    "lägg till",
    "lagg till",
    "make",
    "skapa",
)

_STRUCTURED_INTERMEDIATE_FORCE_HINTS = (
    "json",
    "kontrakt",
    "contract",
    "extrahera",
    "extract",
    "risker",
    "risks",
    "rekommendationer",
    "recommendations",
)

_STRUCTURED_INTERMEDIATE_OPTOUT_HINTS = (
    "håll analysen som vanlig text",
    "keep the analysis as plain text",
    "undvik extra struktur",
    "avoid extra structure",
    "plain text only",
    "text only",
)

_STRUCTURED_REPORT_HINTS = (
    "rapport",
    "report",
    "pdf",
    "docx",
    "structured report",
    "strukturerad",
)

_ANALYSIS_STAGE_HINTS = (
    "analys",
    "analysis",
    "sociologisk",
    "psykologisk",
    "psychological",
    "comparison",
    "jämförelse",
)

_DOCUMENT_PACKAGE_PHRASES: tuple[str, ...] = (
    "dokumentpaket",
    "document package",
    "flera relaterade pdf",
    "multiple related pdf",
    "flera dokument i samma ärende",
    "multiple documents for the same case",
)

_COMPARISON_REQUEST_MARKERS = (
    "compare",
    "comparison",
    "jämför",
    "jämföra",
    "jämförelse",
    "contradiction",
    "motsägelser",
    "skillnader",
    "validate",
    "validation",
    "validera",
    "validering",
    "checklista",
    "checklist",
)

_SAME_RUN_REFERENCE_MARKERS = (
    "same run",
    "samma körning",
    "ladda upp flera pdf",
    "ladda upp flera pdf:er",
    "ladda upp flera dokument",
    "upload multiple pdf",
    "upload several pdf",
    "upload multiple documents",
    *_DOCUMENT_PACKAGE_PHRASES,
)

_EXISTING_REFERENCE_MARKERS = (
    "earlier saved",
    "tidigare sparade",
    "previous material",
    "tidigare material",
    "knowledge base",
    "kunskapsbas",
    "schema",
    "regler",
    "rules",
    "checklista",
    "checklist",
)


def build_discovery_profile(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    planning_state: PlanningState | None = None,
) -> DiscoveryProfile:
    full_text = aggregate_freeform_user_text(conversation)
    capabilities = build_flow_capability_profile(flow)
    flow_defaults = capabilities.to_signal_defaults()
    active_window = (
        build_active_request_window(conversation, flow_defaults=flow_defaults)
        if flow is not None
        else None
    )
    active_conversation = (
        conversation[active_window.start_index :]
        if active_window is not None and active_window.start_index is not None
        else conversation
    )
    planning_state = planning_state or build_planning_state_from_conversation(
        active_conversation,
        flow=flow,
    )
    planning_state_answers = answer_signals_from_planning_state(planning_state)
    active_planning_state_answers = answer_signals_from_planning_state(
        planning_state,
        accepted_sources=_ACTIVE_REQUEST_ANSWER_SOURCES,
    )
    answers = merge_answer_signals(
        extract_answer_signals(conversation),
        planning_state_answers,
    )
    text = (
        active_window.text
        if active_window is not None and active_window.text
        else full_text
    )
    active_answers = merge_answer_signals(
        extract_answer_signals(
            (
                conversation[active_window.start_index :]
                if active_window is not None and active_window.start_index is not None
                else conversation
            )
        ),
        active_planning_state_answers,
    )
    active_explicit_question_ids = {
        question_id
        for question_id in (
            "processing_scope",
            "comparison_scope",
            "primary_runtime_input",
            "flow_input_architecture",
            "document_kind",
            "document_material_scope",
            "terminal_output",
            "docx_output_mode",
            "pdf_generation_mode",
            "final_pdf_type",
            "output_reader",
            "final_output_scope",
            "structured_analysis_need",
            "runtime_metadata_fields",
        )
        if has_explicit_structured_answer(active_conversation, question_id)
    }
    output_intent = resolve_output_intent(
        text,
        active_answers,
        flow_defaults=flow_defaults,
        conversation=active_conversation,
    )
    explicit_input_question_ids = {
        question_id
        for question_id in ("primary_runtime_input", "flow_input_architecture")
        if has_explicit_structured_answer(conversation, question_id)
    }
    input_intent = resolve_input_intent(
        text,
        active_answers,
        flow=flow,
        explicit_question_ids=explicit_input_question_ids,
    )
    explicit_output = output_intent.terminal_output
    default_input_modes = flow_defaults.get("primary_runtime_input", set())
    default_output_mode = flow_defaults.get("terminal_output", set())
    edit_scope = resolve_edit_scope(
        edit_mode=flow is not None,
        capabilities=capabilities,
        active_request_text=text,
        active_answer_signals=active_answers,
        active_explicit_question_ids=active_explicit_question_ids,
        merged_previous_request=(
            active_window.merged_previous_request
            if active_window is not None
            else False
        ),
    )
    prefer_structured_intermediate = should_prefer_structured_intermediate(
        text=text,
        input_intent=input_intent,
        output_intent=output_intent,
        flow_defaults=flow_defaults,
        answers=answers,
    )
    comparison_requested = _comparison_requested(
        text=text,
        answers=answers,
        planning_state=planning_state,
    )
    reference_source = resolve_reference_source(
        text=text,
        answers=answers,
        comparison_requested=comparison_requested,
    )
    return DiscoveryProfile(
        language=resolve_discovery_language(conversation, text),
        text=text,
        active_request_text=text,
        answers=answers,
        flow_defaults=flow_defaults,
        capabilities=capabilities,
        edit_scope=edit_scope,
        input_intent=input_intent,
        output_intent=output_intent,
        planning_state=planning_state,
        flow=flow,
        edit_mode=flow is not None,
        comparison_requested=comparison_requested,
        reference_source=reference_source,
        document_like_input=input_intent.document_runtime_input_requested
        or "documents" in default_input_modes,
        case_like_flow=mentions_any(
            text,
            (
                "case material",
                "case package",
                "ärende",
                "underlag",
                "ticket",
                "tickets",
                "support ticket",
                "support tickets",
                "inquiry",
                "inquiries",
                "triage",
            ),
        )
        or bool(flow_defaults.get("runtime_metadata_fields")),
        audio_like_input=input_intent.audio_requested or "audio" in default_input_modes,
        final_output_text_or_docx=(
            explicit_output in {"structured_text", "docx_document", "pdf_document"}
            or output_intent.content_shape == "structured_report"
            or bool(default_output_mode)
        ),
        prefer_structured_intermediate=prefer_structured_intermediate,
    )


def _comparison_requested(
    *,
    text: str,
    answers: dict[str, set[str]],
    planning_state: PlanningState,
) -> bool:
    if mentions_any(text, _COMPARISON_REQUEST_MARKERS):
        return True
    if "compare_or_validate" in answers.get("post_processing_goal", set()):
        return True
    goal = planning_state.resolved_slots.get("post_processing_goal")
    return goal is not None and goal.value == "compare_or_validate"


def resolve_reference_source(
    *,
    text: str,
    answers: dict[str, set[str]],
    comparison_requested: bool,
) -> ReferenceSourceResolution:
    if not comparison_requested:
        return ReferenceSourceResolution(
            status="not_requested",
            reason="comparison_or_validation_not_requested",
        )

    comparison_scope = answers.get("comparison_scope", set())
    if comparison_scope:
        if comparison_scope.intersection(
            {"same_run_compare", "same_run_multiple_documents"}
        ):
            return ReferenceSourceResolution(
                status="same_run_sources",
                reason="comparison_scope_answer_same_run",
            )
        if "compare_previous_material" in comparison_scope:
            return ReferenceSourceResolution(
                status="existing_flow_or_knowledge",
                reason="comparison_scope_answer_existing_material",
            )
        if "no_direct_compare" in comparison_scope:
            return ReferenceSourceResolution(
                status="not_requested",
                reason="comparison_scope_answer_no_direct_compare",
            )
        return ReferenceSourceResolution(
            status="unclear",
            reason="comparison_scope_answer_unclear",
        )

    if mentions_any(text, _SAME_RUN_REFERENCE_MARKERS):
        return ReferenceSourceResolution(
            status="same_run_sources",
            reason="same_run_reference_text",
        )
    if mentions_any(text, _EXISTING_REFERENCE_MARKERS):
        return ReferenceSourceResolution(
            status="existing_flow_or_knowledge",
            reason="existing_reference_text",
        )
    return ReferenceSourceResolution(
        status="missing",
        reason="comparison_requested_without_reference_source",
    )


def merge_answer_signals(
    primary: dict[str, set[str]],
    supplemental: dict[str, set[str]] | None,
) -> dict[str, set[str]]:
    merged = {key: set(values) for key, values in primary.items()}
    if supplemental is None:
        return merged
    for key, values in supplemental.items():
        merged.setdefault(key, set()).update(values)
    return merged


def answer_signals_from_planning_state(
    planning_state: PlanningState,
    *,
    accepted_sources: frozenset[str] = _PROFILE_ANSWER_SOURCES,
) -> dict[str, set[str]]:
    answers: dict[str, set[str]] = {}
    for slot in planning_state.resolved_slots.values():
        if slot.source not in accepted_sources:
            continue
        answers.setdefault(slot.name, set()).add(slot.value)
    return answers


def default_discovery_assumptions(
    *,
    profile: DiscoveryProfile,
    selected_question_ids: list[str],
    existing_assumptions: list[str],
) -> list[str]:
    assumptions: list[str] = []
    document_scope_slot = profile.planning_state.resolved_slots.get(
        "document_material_scope"
    )
    document_scope_answer_is_user_or_model_owned = (
        "document_material_scope" in profile.answers
        and (
            document_scope_slot is None
            or document_scope_slot.source != "policy_default"
        )
    )
    if (
        "processing_scope" not in profile.answers
        and "processing_scope" not in selected_question_ids
        and implies_single_case(profile.text)
        and not any(
            "körning åt gången" in assumption for assumption in existing_assumptions
        )
    ):
        assumptions.append(
            localized_text(
                profile.language,
                "Antar en körning åt gången tills du säger att flera paket ska hanteras tillsammans.",
                "Assuming one run at a time unless you later say multiple packages should be handled together.",
            )
        )
    if (
        not document_scope_answer_is_user_or_model_owned
        and "document_material_scope" not in selected_question_ids
        and profile.document_like_input
        and implies_single_primary_document(profile.text)
        and not any(
            "huvuddokument" in assumption for assumption in existing_assumptions
        )
    ):
        assumptions.append(
            localized_text(
                profile.language,
                "Antar ett huvuddokument per körning tills du säger att ett dokumentpaket ska stödjas.",
                "Assuming one primary document per run unless you later say a document package must be supported.",
            )
        )
    if (
        profile.prefer_structured_intermediate
        and "structured_analysis_need" not in selected_question_ids
        and not any(
            "mellanliggande strukturerad data" in assumption.casefold()
            for assumption in existing_assumptions
        )
    ):
        assumptions.append(
            localized_text(
                profile.language,
                "Antar att mellanliggande strukturerad data används i analyssteg där det förbättrar kvalitet och återanvändning.",
                "Assuming intermediate structured data is used in analysis steps where it improves quality and reuse.",
            )
        )
    return assumptions


def expresses_task_intent(text: str) -> bool:
    raw_text = text.casefold()
    normalized = normalize_discovery_text(text)
    # A bare question mark usually means the user is asking about the builder,
    # not asking the builder to create or change a flow.
    if "?" in raw_text and not mentions_any(normalized, _QUESTION_ACTION_MARKERS):
        return False
    return contains_any_token_prefix(
        normalized,
        (*_TASK_VERB_PREFIXES_SV, *_TASK_VERB_PREFIXES_EN),
    ) or any(token in normalized.split() for token in _TASK_VERB_EXACT_TOKENS)


def count_distinct_task_verbs(text: str) -> int:
    normalized = normalize_discovery_text(text)
    tokens = normalized.split()
    matches = {
        verb
        for verb in (*_TASK_VERB_PREFIXES_SV, *_TASK_VERB_PREFIXES_EN)
        if any(token.startswith(verb) for token in tokens)
    }
    matches.update(token for token in _TASK_VERB_EXACT_TOKENS if token in tokens)
    return len(matches)


def should_prefer_structured_intermediate(
    *,
    text: str,
    input_intent: InputIntentResolution,
    output_intent: OutputIntentResolution,
    flow_defaults: dict[str, set[str]],
    answers: dict[str, set[str]],
) -> bool:
    structured_answer = answers.get("structured_analysis_need", set())
    if "text_only_analysis" in structured_answer:
        return False
    if "use_structured_analysis" in structured_answer:
        return True
    if mentions_any(text, _STRUCTURED_INTERMEDIATE_OPTOUT_HINTS):
        return False
    if mentions_any(text, _STRUCTURED_INTERMEDIATE_FORCE_HINTS):
        return True

    document_like_input = (
        input_intent.document_runtime_input_requested
        or "documents"
        in flow_defaults.get(
            "primary_runtime_input",
            set(),
        )
    )
    audio_like_input = input_intent.audio_requested or "audio" in flow_defaults.get(
        "primary_runtime_input",
        set(),
    )
    if not (document_like_input or audio_like_input):
        return False

    structured_deliverable = (
        output_intent.terminal_output in {"pdf_document", "docx_document"}
        or output_intent.content_shape == "structured_report"
        or mentions_any(text, _STRUCTURED_REPORT_HINTS)
    )
    if not structured_deliverable:
        return False

    task_verb_count = count_distinct_task_verbs(text)
    if task_verb_count >= 3:
        return True
    return task_verb_count >= 2 and mentions_any(text, _ANALYSIS_STAGE_HINTS)


def mentions_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def infer_discovery_language(text: str) -> DiscoveryLanguage:
    if mentions_any(
        text,
        (
            " jag ",
            " ska ",
            " vill ",
            " flöde",
            " dokument",
            " underlag",
            " jämför",
            " rapport",
            " ärende",
            " och ",
            " att ",
            " för ",
        ),
    ) or any(char in text for char in ("å", "ä", "ö")):
        return "sv"
    return "en"


def resolve_discovery_language(
    conversation: list[ConversationMessage],
    text: str,
) -> DiscoveryLanguage:
    for message in reversed(conversation):
        if message.role != "user":
            continue
        ui_language = ui_language_from_metadata(message.metadata)
        if ui_language in {"sv", "en"}:
            return ui_language
    return infer_discovery_language(text)
