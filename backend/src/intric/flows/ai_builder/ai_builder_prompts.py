"""Prompt assembly and conversation trimming for the AI Flow Builder."""

from __future__ import annotations

from typing import Any

from intric.flows.domain.flow import Flow
from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from intric.flows.ai_builder.ai_builder_flow_context import (
    build_available_kbs_context,
    build_available_models_context,
    build_flow_context,
    build_plan_summary,
    build_step_ref_mapping,
)
from intric.flows.ai_builder.ai_builder_discovery import (
    build_discovery_guidance,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    canonical_question_id,
    build_framework_guardrails_block,
    extract_answer_signals,
    mentions_output_change,
    mentions_runtime_metadata,
    resolve_output_intent,
    runtime_metadata_requested,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack import (
    _KNOWLEDGE_PACK_ANTI_PATTERNS,
    _KNOWLEDGE_PACK_CONTRACTS,
    _KNOWLEDGE_PACK_EDIT_MODE,
    _KNOWLEDGE_PACK_FLOW_ARCHITECTURE,
    _KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG,
    _KNOWLEDGE_PACK_IO_INTELLIGENCE,
    _KNOWLEDGE_PACK_STEP_DESIGN,
    _KNOWLEDGE_PACK_VARIABLE_SYSTEM,
    _ROLE_AND_PROTOCOL,
    _STRUCTURED_REFERENCE_BLOCK,
    _VALIDATION_REPAIR_EXAMPLES,
)
from intric.flows.ai_builder.ai_builder_recipe_selector import select_relevant_recipes
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_confirmed_requirements_prompt_block,
    build_requirements_version,
    resolve_requirements_state,
)

__all__ = [
    "build_available_kbs_context",
    "build_available_models_context",
    "build_clarification_hints",
    "build_flow_context",
    "build_plan_summary",
    "build_step_ref_mapping",
    "build_system_prompt",
    "compute_conversation_token_budget",
    "has_confirmed_requirements",
    "trim_conversation_for_context",
]


def build_system_prompt(
    *,
    flow_context: str | None = None,
    available_models: list[dict[str, str]] | None = None,
    available_knowledge_bases: list[dict[str, str]] | None = None,
    planner_hints: str | None = None,
    ui_language: str | None = None,
    confirmed_requirements: dict[str, Any] | None = None,
    is_edit_mode: bool = False,
) -> str:
    """Build the complete system prompt for the AI builder LLM.

    Sections are injected conditionally based on conversation phase:
    - Discovery (no confirmed requirements): core + architecture only
    - Proposal (confirmed): core + recipes + contracts + anti-patterns
    - Edit mode: core + edit-specific knowledge, skip create-only content
    """
    # Core sections — always present
    sections = [
        _ROLE_AND_PROTOCOL,
        _STRUCTURED_REFERENCE_BLOCK,
        _KNOWLEDGE_PACK_FLOW_ARCHITECTURE,
        build_framework_guardrails_block(),
        _KNOWLEDGE_PACK_VARIABLE_SYSTEM,
    ]

    if is_edit_mode:
        # Edit mode: add edit-specific knowledge, skip heavy create-only content
        sections.append(_KNOWLEDGE_PACK_EDIT_MODE)
        sections.append(_KNOWLEDGE_PACK_CONTRACTS)
        sections.append(_KNOWLEDGE_PACK_STEP_DESIGN)
    elif confirmed_requirements is not None:
        # Proposal phase: include full recipe/pattern knowledge
        sections.append(_KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG)
        sections.append(_KNOWLEDGE_PACK_CONTRACTS)
        answer_signals = _extract_signals_from_requirements(confirmed_requirements)
        freeform_summary = (
            confirmed_requirements.get("summary", "")
            if isinstance(confirmed_requirements, dict)
            else ""
        )
        sections.append(select_relevant_recipes(answer_signals, freeform_summary))
        sections.append(_KNOWLEDGE_PACK_IO_INTELLIGENCE)
        sections.append(_KNOWLEDGE_PACK_ANTI_PATTERNS)
        sections.append(_KNOWLEDGE_PACK_STEP_DESIGN)
        sections.append(_VALIDATION_REPAIR_EXAMPLES)
    else:
        # Discovery phase: lightweight — only instructions guide
        sections.append(_KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG)

    if confirmed_requirements:
        requirements_payload = RequirementsSummaryPayload.model_validate(
            confirmed_requirements
        )
        requirements_version = build_requirements_version(requirements_payload)
        requirements_block = build_confirmed_requirements_prompt_block(
            [
                ConversationMessage(
                    role="tool",
                    metadata={
                        "requirements_summary": requirements_payload.model_dump(
                            mode="json"
                        ),
                        "requirements_version": requirements_version,
                    },
                ),
                ConversationMessage(
                    role="user",
                    metadata={
                        "requirements_confirmed": True,
                        "requirements_version": requirements_version,
                    },
                ),
            ]
        )
        if requirements_block:
            sections.append(requirements_block)

    if flow_context:
        sections.append(f"\n## Aktuellt flöde\n\n{flow_context}")

    if available_models:
        model_lines = "\n".join(
            f"- `{model['ref']}`: {model['name']} ({model.get('provider', 'unknown')})"
            for model in available_models
        )
        sections.append(f"\n## Tillgängliga modeller\n\n{model_lines}")

    if available_knowledge_bases:
        kb_lines = "\n".join(
            f"- `{kb['ref']}`: {kb['name']}"
            + (f" — {kb['description']}" if kb.get("description") else "")
            for kb in available_knowledge_bases
        )
        sections.append(f"\n## Tillgängliga kunskapsbaser\n\n{kb_lines}")

    if planner_hints:
        sections.append(f"\n## Planeringshintar\n\n{planner_hints}")

    if ui_language == "sv":
        sections.append(
            "\n## Aktivt gränssnittsspråk\n\n"
            "- All användarvänd text, alla strukturerade frågor, kravsammanfattningar och "
            "planförklaringar ska skrivas på svenska.\n"
            "- Blanda inte svenska och engelska i samma session."
        )
    elif ui_language == "en":
        sections.append(
            "\n## Active UI language\n\n"
            "- All user-facing text, structured questions, requirements summaries, and plan "
            "explanations must be written in English.\n"
            "- Do not mix English and Swedish within the same session."
        )

    return "\n\n".join(sections)


def build_clarification_hints(
    *,
    conversation: list[ConversationMessage],
    latest_user_message: str,
    flow: Flow | None = None,
) -> str | None:
    """Derive targeted planning hints for high-impact unresolved ambiguities."""
    text = latest_user_message.casefold()
    discovery_guidance = build_discovery_guidance(conversation, flow=flow)
    if discovery_guidance is not None:
        return discovery_guidance

    answered_ids = {
        question_id
        for question_id in (
            _extract_question_id(message) for message in conversation
        )
        if question_id is not None
    }

    hints: list[str] = []
    answer_signals = extract_answer_signals(conversation)
    flow_defaults = build_flow_discovery_defaults(flow)
    aggregate_text = aggregate_freeform_user_text(conversation)
    intent_text = "\n".join(part for part in (aggregate_text, text) if part)
    output_intent = resolve_output_intent(
        intent_text,
        answer_signals,
        flow_defaults=flow_defaults,
    )
    input_intent = resolve_input_intent(
        intent_text,
        answer_signals,
        flow=flow,
    )
    resolved_output = output_intent.terminal_output
    resolved_docx_mode = output_intent.docx_output_mode
    resolved_pdf_mode = output_intent.pdf_generation_mode

    if _needs_pdf_scope_question(text, answered_ids):
        hints.append(
            "- Frågegate: använd `ask_structured_question` innan `propose_flow` för att avgöra "
            "om flödet ska stödja en PDF i taget eller flera dokument i samma körning. "
            "Använd `question_id=\"document_material_scope\"` med tydliga alternativ för enkel respektive fler-dokument-körning."
        )

    if _needs_docx_mode_question(
        answered_ids,
        resolved_output=resolved_output,
        resolved_docx_mode=resolved_docx_mode,
    ):
        hints.append(
            "- Frågegate: använd `ask_structured_question` innan `propose_flow` för att avgöra "
            "hur DOCX-rapporten ska skapas. Använd `question_id=\"docx_output_mode\"` med alternativ "
            "för mallbaserad DOCX respektive genererad DOCX utan mall."
        )

    if _needs_pdf_generation_mode_question(
        answered_ids,
        resolved_output=resolved_output,
        resolved_pdf_mode=resolved_pdf_mode,
    ):
        hints.append(
            "- Frågegate: använd `ask_structured_question` innan `propose_flow` för att avgöra "
            "om PDF-resultatet ska vara en vanlig genererad PDF eller om användaren egentligen "
            "efterfrågar en fast PDF-mall. Använd `question_id=\"pdf_generation_mode\"` och var "
            "tydlig med att inbyggd mallfyllning bara stöds för DOCX/Word."
        )

    if input_intent.primary_runtime_input in {"audio", "documents", "text_and_documents"}:
        hints.append(
            "- Implementationshint: eftersom användaren laddar upp PDF/dokument/filer vid körning ska "
            "relevanta `flow_input`-steg använda `input_config.runtime_input.enabled=true` "
            "så att 'Ta emot filer vid körning' aktiveras."
        )

    if input_intent.audio_requested:
        hints.append(
            "- Implementationshint: eftersom användaren nämner ljud/transkribering ska "
            "relevanta steg använda `input_type=\"audio\"`, `output_mode=\"transcribe_only\"` "
            "och `output_type=\"text\"`."
        )

    if _mentions_form_field_needs(text):
        hints.append(
            "- Designhint: eftersom användaren beskriver värden som ska anges eller väljas vid körning "
            "(t.ex. språk, fokus, datum, ärendenummer eller nivå) ska dessa modelleras som "
            "`form_fields` så att senare steg kan använda dem som variabler."
        )

    if _mentions_structured_extraction(text):
        hints.append(
            "- Designhint: om planen innehåller steg som ska extrahera namngivna fält, listor eller "
            "objekt för senare återanvändning ska dessa steg använda `output_type=\"json\"` och ett "
            "fullständigt `output_contract`. Presentera inte ett JSON-steg utan kontrakt."
        )

    if resolved_docx_mode == "template_fill_docx":
        hints.append(
            "- Implementationshint: eftersom användaren nämner mallar/template_fill ska "
            "relevanta steg använda `output_mode=\"template_fill\"` och `output_type=\"docx\"`. "
            "Användaren behöver koppla DOCX-mallen manuellt efter att flödet skapats."
        )

    if resolved_pdf_mode == "pdf_template_requested":
        hints.append(
            "- Designhint: användaren verkar efterfråga en fast PDF-mall. Modellera inte detta som "
            "DOCX-mallfyllning, eftersom native template filling bara stöds för DOCX/Word. Håll PDF-flödet "
            "ärligt som genererad PDF, eller be användaren byta till en DOCX-mall om exakt mallfyllning är avgörande."
        )
    elif resolved_output is None and _mentions_template_need(text):
        hints.append(
            "- Designhint: om användaren menar en Word-mall ska relevanta steg använda "
            "`output_mode=\"template_fill\"` och `output_type=\"docx\"`. Om användaren i stället menar en "
            "PDF-mall ska du först klargöra det via `pdf_generation_mode`."
        )

    if resolved_output is not None and not mentions_output_change(text):
        hints.append(
            "- Redan löst designval: slutformatet är redan känt från tidigare svar eller befintligt flöde. "
            "Öppna inte en ny fråga om output-format under ett annat namn om användaren inte uttryckligen ändrar det."
        )

    if (
        runtime_metadata_requested(answer_signals)
        or flow_defaults.get("runtime_metadata_fields")
    ) and not mentions_runtime_metadata(text):
        hints.append(
            "- Redan löst designval: runtime-metadata är redan avgjort. "
            "Fråga inte igen om formulärfält eller metadata om användaren inte uttryckligen vill ändra dem."
        )

    if not hints:
        return None

    return "\n".join(hints)


def compute_conversation_token_budget(
    *,
    litellm_model: str | None,
    model_max_input_tokens: int | None,
    system_prompt_tokens: int,
    max_output_tokens: int,
    safety_buffer_tokens: int,
    minimum_budget_tokens: int,
    unknown_model_context_window_tokens: int | None = None,
) -> int:
    """Compute available token budget for conversation history.

    Uses the model's actual context window (via LiteLLM) minus the system prompt,
    output reservation, and an explicit safety buffer. Uses the stored model
    budget or an explicit configured fallback when LiteLLM has no match.
    """
    from intric.model_providers.domain.model_defaults import lookup_model_defaults

    defaults = None
    if litellm_model:
        bare_name = litellm_model.split("/", 1)[-1] if "/" in litellm_model else None
        defaults = lookup_model_defaults(litellm_model, bare_name)

    context_window = (
        (defaults.max_input_tokens if defaults else None)
        or model_max_input_tokens
        or unknown_model_context_window_tokens
    )
    if context_window is None:
        raise ValueError("Planner model has no known context window.")

    budget = context_window - system_prompt_tokens - max_output_tokens - safety_buffer_tokens
    return max(budget, minimum_budget_tokens)


def trim_conversation_for_context(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
) -> list[dict[str, Any]]:
    """Trim conversation history to fit within the provided token budget.

    The budget should come from compute_conversation_token_budget() which
    derives it from the model's actual context window.
    """
    if max_tokens >= _estimate_group_tokens(messages):
        return list(messages)

    groups: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        group = [message]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            tool_index = index + 1
            while tool_index < len(messages) and messages[tool_index].get("role") == "tool":
                group.append(messages[tool_index])
                tool_index += 1
            index = tool_index
        else:
            index += 1
        groups.append(group)

    kept_groups: list[list[dict[str, Any]]] = []
    consumed_tokens = 0
    for group in reversed(groups):
        group_tokens = _estimate_group_tokens(group)
        if kept_groups and consumed_tokens + group_tokens > max_tokens:
            break
        kept_groups.append(group)
        consumed_tokens += group_tokens

    kept_groups.reverse()
    trimmed: list[dict[str, Any]] = []
    for group in kept_groups:
        trimmed.extend(group)
    return trimmed


def _estimate_group_tokens(group: list[dict[str, Any]]) -> int:
    return sum(_estimate_message_tokens(message) for message in group)


def _estimate_message_tokens(message: dict[str, Any]) -> int:
    chunks: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        chunks.append(content)

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            chunks.append(str(tool_call))

    tool_call_id = message.get("tool_call_id")
    if isinstance(tool_call_id, str):
        chunks.append(tool_call_id)

    if not chunks:
        return 1

    # Use // 3 instead of // 4: Swedish compound words average fewer chars
    # per token than English, so the conservative factor prevents undercount.
    return max(1, sum(max(1, len(chunk) // 3) for chunk in chunks) + 4)


def _extract_question_id(message: ConversationMessage) -> str | None:
    metadata = message.metadata
    if not isinstance(metadata, dict):
        return None
    question_answer = metadata.get("question_answer")
    if not isinstance(question_answer, dict):
        return None
    question_id = question_answer.get("question_id")
    return canonical_question_id(question_id) if isinstance(question_id, str) else None


def _needs_pdf_scope_question(text: str, answered_ids: set[str]) -> bool:
    if "document_material_scope" in answered_ids:
        return False
    mentions_documents = any(token in text for token in ("pdf", "dokument", "dokumen"))
    mentions_plurality = any(
        token in text
        for token in ("flera", "ett eller flera", "många", "samtidigt", "mellan dokument")
    )
    mentions_comparison = any(
        token in text for token in ("jämför", "jämföra", "jämförelse", "motsägelser", "skillnader")
    )
    return mentions_documents and (mentions_plurality or mentions_comparison)


def _needs_docx_mode_question(
    answered_ids: set[str],
    *,
    resolved_output: str | None,
    resolved_docx_mode: str | None,
) -> bool:
    if "docx_output_mode" in answered_ids:
        return False
    if resolved_output != "docx_document":
        return False
    return resolved_docx_mode is None


def _needs_pdf_generation_mode_question(
    answered_ids: set[str],
    *,
    resolved_output: str | None,
    resolved_pdf_mode: str | None,
) -> bool:
    if "pdf_generation_mode" in answered_ids:
        return False
    return resolved_output == "pdf_document" and resolved_pdf_mode == "pdf_template_requested"


def _mentions_form_field_needs(text: str) -> bool:
    return any(
        token in text
        for token in (
            "ska kunna ange",
            "ska kunna välja",
            "ska fylla i",
            "fyll i",
            "ange följande",
            "önskat språk",
            "välja språk",
            "fokus för analysen",
            "ärendenummer",
            "kort beskrivning",
            "politisk nivå",
            "nämnd",
        )
    )


def _mentions_structured_extraction(text: str) -> bool:
    return any(
        token in text
        for token in (
            "json",
            "strukturerad",
            "strukturerade fält",
            "fält, till exempel",
            "extrahera",
            "lista med",
            "returnera enbart giltig json",
        )
    )


def _mentions_template_need(text: str) -> bool:
    return any(token in text for token in ("mall", "template", "fylla i"))


def _extract_signals_from_requirements(
    confirmed_requirements: dict[str, Any] | None,
) -> dict[str, set[str]]:
    """Extract answer signals from confirmed requirements for recipe selection."""
    if not confirmed_requirements or not isinstance(confirmed_requirements, dict):
        return {}
    signals: dict[str, set[str]] = {}
    input_desc = confirmed_requirements.get("input_description", "").lower()
    output_desc = confirmed_requirements.get("output_description", "").lower()
    combined = f"{input_desc} {output_desc}"

    input_intent = resolve_input_intent(input_desc, {})
    if input_intent.primary_runtime_input == "audio":
        signals.setdefault("input_material_mode", set()).add("audio")
    if input_intent.primary_runtime_input == "documents":
        signals.setdefault("input_material_mode", set()).add("documents")
    if input_intent.primary_runtime_input == "text":
        signals.setdefault("input_material_mode", set()).add("text")
    if input_intent.primary_runtime_input == "text_and_documents":
        signals.setdefault("input_material_mode", set()).add("text_and_documents")
    if "docx" in combined:
        signals.setdefault("final_output_mode", set()).add("docx_document")
    if "pdf" in output_desc:
        signals.setdefault("final_output_mode", set()).add("pdf_document")
    if "json" in combined:
        signals.setdefault("final_output_mode", set()).add("structured_json")
    if "jämför" in combined or "compar" in combined:
        signals.setdefault("comparison_scope", set()).add("comparison")
    return signals


def has_confirmed_requirements(conversation: list[ConversationMessage]) -> bool:
    """Check if the latest requirements summary is confirmed."""
    return resolve_requirements_state(conversation).confirmed
