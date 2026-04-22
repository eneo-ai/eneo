from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    mentions_sectioned_form_intake,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    needs_structured_extraction,
    resolve_output_intent,
    runtime_metadata_requested,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    degrades_document_entry_to_generic_file,
    has_real_audio_transcription_step,
    mixed_audio_document_input_requested,
    uses_pseudo_transcription_without_audio_step,
)
from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_plan_store import format_revision_feedback
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
    detect_planner_pattern_signals,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from intric.flows.domain.flow import Flow

# Markers that indicate the user explicitly wants structured JSON extraction
# for downstream reuse — NOT just any mention of "json" in passing.
_JSON_CONTRACT_MARKERS: tuple[str, ...] = (
    "json",
    "strukturerad data",
    "structured data",
    "extract fields",
    "extrahera fält",
    "output contract",
    "output_contract",
)

# Markers that indicate the user wants a human-readable terminal result,
# which means output_type=text is correct — no JSON warning needed.
_HUMAN_READABLE_TERMINAL_MARKERS: tuple[str, ...] = (
    "sammanfatt",
    "summarize",
    "summary",
    "rapport",
    "report",
    "analys",
    "analysis",
    "beslut",
    "decision",
    "overview",
    "överblick",
    "skriv",
    "write",
)

_AUDIO_STANDALONE_MARKERS: tuple[str, ...] = (
    "audio",
    "ljud",
    "transkrib",
    "transcrib",
    "inspelning",
    "recording",
)

_FIELD_REUSE_MARKERS: tuple[str, ...] = (
    "specific fields",
    "specific json fields",
    "use the fields",
    "använd fälten",
    "specifika fälten",
    "namngivna fält",
    "key clauses",
    "nyckelfakta",
)

_MULTI_DOC_COMPARE_MARKERS: tuple[str, ...] = (
    "compare",
    "jämför",
    "jämföra",
    "multiple documents",
    "flera dokument",
    "document package",
    "dokumentpaket",
)


def build_conversation_aware_quality_feedback(
    conversation: list[ConversationMessage] | list[Mapping[str, Any]],
    spec: FlowDraftSpecCore,
    *,
    flow: Flow | None = None,
) -> str | None:
    issues: list[str] = []
    answer_signals = extract_answer_signals(conversation)
    text = aggregate_freeform_user_text(conversation)
    requirements_state = resolve_requirements_state(
        [
            item
            if isinstance(item, ConversationMessage)
            else ConversationMessage.model_validate(item)
            for item in conversation
        ]
    )
    requirements_text = build_requirements_signal_text(
        requirements_state.latest_summary.model_dump(mode="json")
        if requirements_state.latest_summary is not None
        else None
    )
    signal_text = "\n".join(part for part in (text, requirements_text) if part)
    planner_patterns = detect_planner_pattern_signals(signal_text)
    output_intent = resolve_output_intent(text, answer_signals)

    if runtime_metadata_requested(answer_signals) and not spec.form_fields:
        issues.append(
            "Användaren har bett om återanvändbara metadata vid körning men planen saknar "
            "`form_fields`. Lägg till relevanta formulärfält i stället för att gömma dessa värden i prompttext."
        )

    if mentions_sectioned_form_intake(text) and not spec.form_fields:
        issues.append(
            "Konversationen beskriver sektionerad fritextinsamling per rubrik/sektion, men planen saknar "
            "`form_fields`. Modellera varje rubrik som ett eget textfält i `form_fields` i stället för att "
            "bygga ett separat insamlingssteg per sektion, och låt senare steg använda dessa fält via "
            "`uses_form_fields` för att skapa slutdokumentet."
        )

    if planner_patterns.rich_document_workflow:
        if planner_patterns.needs_form_fields and not spec.form_fields:
            issues.append(
                "Behovet beskriver ett dokumentbaserat flöde som också kräver manuella kompletteringar eller "
                "inmatningsfält, men planen saknar `form_fields`. Modellera dessa värden som form_fields i "
                "stället för att gömma dem i instruktionstexten."
            )
        if (
            planner_patterns.prefers_structured_intermediate
            and not _has_json_contract_step(spec)
        ):
            issues.append(
                "Behovet beskriver ett dokumentflöde som ska återanvända strukturerad analys, men planen saknar "
                'ett tydligt JSON-steg med `output_contract`. Lägg till ett mellanliggande `output_type="json"`-steg '
                "innan slutlig rapport eller dokumentleverans."
            )
        if planner_patterns.prefers_quality_step and len(spec.steps) < 3:
            issues.append(
                "Behovet beskriver ett mer genomarbetat dokumentflöde med analys, granskning eller kvalitetssäkring, "
                "men planen kollapsar fortfarande till för få steg. Lägg till minst ett mellanliggande analys- eller "
                "granskningssteg innan slutleveransen."
            )

    explicit_output = output_intent.terminal_output
    if (
        explicit_output == "pdf_document"
        and spec.steps[-1].output_type != OutputType.PDF
    ):
        issues.append(
            "Användaren har valt PDF som slutartefakt men sista steget producerar inte PDF. "
            "Justera slutstegets output_type så att det matchar användarens val."
        )
    if (
        explicit_output == "docx_document"
        and spec.steps[-1].output_type != OutputType.DOCX
    ):
        issues.append(
            "Användaren har valt DOCX som slutartefakt men sista steget producerar inte DOCX. "
            "Justera slutstegets output_type så att det matchar användarens val."
        )
    intermediate_document_feedback = _non_terminal_document_output_feedback(
        explicit_output=explicit_output,
        spec=spec,
        flow=flow,
    )
    if intermediate_document_feedback is not None:
        issues.append(intermediate_document_feedback)

    if needs_structured_extraction(
        text,
        answer_signals,
        step_count=len(spec.steps),
        terminal_output_type=spec.steps[-1].output_type,
    ) and not _has_json_contract_step(spec):
        issues.append(
            "Planen verkar behöva strukturerad extraktion för vidare återanvändning, men saknar ett "
            '`output_type="json"`-steg med `output_contract`. Lägg till ett tydligt JSON-extraktionssteg '
            "innan den slutliga text- eller dokumentproduktionen."
        )

    # Check: missing JSON contract when conversation explicitly asks for structured extraction
    # Anti-over-structuring guardrail: only warn when the user explicitly wants JSON/structured
    # extraction for downstream reuse — never for simple human-readable terminal output.
    if _conversation_requests_json_contract(text) and not _has_json_contract_step(spec):
        if not _terminal_step_is_human_readable_only(text, spec):
            issues.append(
                "Konversationen nämner strukturerad extraktion (JSON, fält, kontrakt) men inget steg "
                'använder `output_type="json"` med `output_contract`. Lägg till ett JSON-extraktionssteg '
                "om data ska återanvändas i nästa steg eller av ett externt system."
            )

    # Check: missing audio transcription step when audio is mentioned standalone
    if _conversation_mentions_audio(text) and not _spec_handles_audio(spec):
        if not mixed_audio_document_input_requested(text, flow=flow):
            issues.append(
                'Konversationen nämner ljud/transkribering men inget steg har `input_type="audio"` '
                'eller `output_mode="transcribe_only"`. Lägg till ett dedikerat transkriberingssteg.'
            )

    if (
        _conversation_requests_field_reuse(text)
        and _has_json_contract_step(spec)
        and not _spec_uses_input_bindings(spec)
    ):
        issues.append(
            "Konversationen antyder återanvändning av specifika fält från strukturerad extraktion, men planen saknar "
            "`uses_previous_fields` i efterföljande steg. Deklarera explicita JSON-fält vidare när nästa steg behöver utvalda datapunkter."
        )

    if _conversation_requests_multi_document_compare(
        text
    ) and not _spec_uses_all_previous_steps(spec):
        issues.append(
            "Konversationen beskriver jämförelse eller samlad analys av flera dokument, men inget steg använder "
            '`input_source="all_previous_steps"`. Använd en aggregerande eller jämförande koppling när flera dokument ska behandlas tillsammans.'
        )

    if (
        output_intent.docx_output_mode == "template_fill_docx"
        and not _spec_uses_template_fill(spec)
    ):
        issues.append(
            "Konversationen efterfrågar mallbaserad DOCX-generering men planen saknar ett steg med "
            '`output_mode="template_fill"`. Använd template_fill när ett Word-dokument ska fyllas från en mall.'
        )

    if output_intent.docx_output_mode == "generated_docx" and _spec_uses_template_fill(
        spec
    ):
        issues.append(
            "Konversationen efterfrågar genererad DOCX utan mall, men planen använder fortfarande "
            '`output_mode="template_fill"`. Använd inte template_fill när användaren uttryckligen '
            "valt genererad DOCX utan mall."
        )

    if mixed_audio_document_input_requested(text, flow=flow):
        if degrades_document_entry_to_generic_file(spec, flow=flow):
            issues.append(
                "Användaren verkar vilja lägga till ljud/transkribering ovanpå ett befintligt dokumentflöde, "
                'men planen degraderar den dokumentbaserade ingången till generisk `input_type="file"`. '
                "Gör inte om ett dokumentflöde till allmän filinput bara för att få plats med ljud."
            )
        if uses_pseudo_transcription_without_audio_step(spec):
            issues.append(
                "Planen beskriver transkribering i instruktionerna men saknar ett riktigt "
                'transkriberingssteg (`input_type="audio"`, `output_mode="transcribe_only"`, '
                '`output_type="text"`). Faka inte transkribering inne i ett dokument- eller JSON-steg.'
            )
        if not has_real_audio_transcription_step(spec):
            issues.append(
                "När användaren vill kombinera ljudtranskribering och dokument i samma ändring måste planen "
                "först lösa inmatningsarkitekturen ärligt. Eneo-flöden stöder bara ett `flow_input`-steg, "
                "så planen ska antingen behålla dokument som primär indata eller byta till en riktig "
                "audio-first-arkitektur med ett transkriberingssteg — inte låtsas att båda ryms via prompttext."
            )

    if not issues:
        return None
    return format_revision_feedback("Quality issues", issues)


def _has_json_contract_step(spec: FlowDraftSpecCore) -> bool:
    for index, step in enumerate(spec.steps):
        if step.output_type != OutputType.JSON:
            continue
        if step.output_contract is None:
            continue
        if index == len(spec.steps) - 1 and len(spec.steps) == 1:
            continue
        return True
    return False


def _conversation_requests_json_contract(text: str) -> bool:
    """True when the user explicitly asks for structured JSON extraction."""
    return any(marker in text for marker in _JSON_CONTRACT_MARKERS)


def _terminal_step_is_human_readable_only(text: str, spec: FlowDraftSpecCore) -> bool:
    """Anti-over-structuring guardrail.

    Returns True when the final step is clearly meant to produce human-readable
    output (summary, report, analysis) and there is no explicit mention of
    downstream JSON consumption or field reuse.
    """
    if not spec.steps:
        return False
    terminal = spec.steps[-1]
    if terminal.output_type not in {OutputType.TEXT, OutputType.DOCX, OutputType.PDF}:
        return False
    # If the conversation explicitly mentions downstream reuse, don't suppress.
    downstream_markers = (
        "downstream",
        "vidare",
        "reuse",
        "återanvänd",
        "next step",
        "nästa steg",
    )
    if any(marker in text for marker in downstream_markers):
        return False
    return any(marker in text for marker in _HUMAN_READABLE_TERMINAL_MARKERS)


def _conversation_mentions_audio(text: str) -> bool:
    """True when the conversation mentions audio/transcription."""
    return any(marker in text for marker in _AUDIO_STANDALONE_MARKERS)


def _spec_handles_audio(spec: FlowDraftSpecCore) -> bool:
    """True when at least one step accepts audio input or uses transcribe_only mode."""
    return any(
        step.input_type == InputType.AUDIO
        or step.output_mode == OutputMode.TRANSCRIBE_ONLY
        for step in spec.steps
    )


def _conversation_requests_field_reuse(text: str) -> bool:
    return any(marker in text for marker in _FIELD_REUSE_MARKERS)


def _conversation_requests_multi_document_compare(text: str) -> bool:
    return any(marker in text for marker in _MULTI_DOC_COMPARE_MARKERS)


def _spec_uses_input_bindings(spec: FlowDraftSpecCore) -> bool:
    return any(step.input_bindings for step in spec.steps)


def _spec_uses_all_previous_steps(spec: FlowDraftSpecCore) -> bool:
    return any(
        step.input_source == InputSource.ALL_PREVIOUS_STEPS for step in spec.steps
    )


def _spec_uses_template_fill(spec: FlowDraftSpecCore) -> bool:
    return any(step.output_mode == OutputMode.TEMPLATE_FILL for step in spec.steps)


def _non_terminal_document_output_feedback(
    *,
    explicit_output: str | None,
    spec: FlowDraftSpecCore,
    flow: Flow | None,
) -> str | None:
    if flow is None or explicit_output not in {"pdf_document", "docx_document"}:
        return None

    original_steps = sorted(flow.steps, key=lambda step: step.step_order)
    if len(spec.steps) != len(original_steps) or len(spec.steps) < 2:
        return None

    original_terminal_output = original_steps[-1].output_type
    requested_terminal_output = "pdf" if explicit_output == "pdf_document" else "docx"
    if original_terminal_output == requested_terminal_output:
        return None

    converted_non_terminal_steps: list[str] = []
    template_fill_steps: list[str] = []
    for original_step, planned_step in zip(
        original_steps[:-1], spec.steps[:-1], strict=False
    ):
        original_is_document_output = original_step.output_type in {"pdf", "docx"}
        planned_is_document_output = planned_step.output_type in {
            OutputType.PDF,
            OutputType.DOCX,
        }
        if not original_is_document_output and planned_is_document_output:
            converted_non_terminal_steps.append(planned_step.name)
        if planned_step.output_mode == OutputMode.TEMPLATE_FILL:
            template_fill_steps.append(planned_step.name)

    if not converted_non_terminal_steps and not template_fill_steps:
        return None

    details: list[str] = []
    if converted_non_terminal_steps:
        details.append(
            "mellanliggande steg har bytts till dokumentutdata: "
            + ", ".join(converted_non_terminal_steps)
        )
    if template_fill_steps:
        details.append(
            "template_fill används på icke-terminala steg: "
            + ", ".join(template_fill_steps)
        )

    return (
        "Användaren verkar bara vilja ändra slutformatet. Ändra inte mellanliggande analyssteg "
        "till DOCX/PDF eller `template_fill` när de tidigare var text/json-steg. Håll upstream-stegen "
        "som analyssteg och lägg dokumentgenereringen på slutsteget. Problem: "
        + "; ".join(details)
        + "."
    )
