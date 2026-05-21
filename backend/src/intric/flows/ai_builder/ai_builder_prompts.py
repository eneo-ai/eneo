# pyright: reportUnusedFunction=false

"""Prompt assembly and conversation trimming for the AI Flow Builder."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_action_policy import (
    PlannerActionPolicy,
    render_action_policy_prompt_block,
)
from intric.flows.ai_builder.ai_builder_ask_question_contract import (
    render_ask_question_vocabulary_block,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    question_answer_from_metadata,
    question_answer_question_id,
)
from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_discovery import (
    build_discovery_guidance,
)
from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    should_prefer_structured_intermediate,
)
from intric.flows.ai_builder.ai_builder_flow_context import (
    build_available_kbs_context,
    build_available_mcp_context,
    build_available_models_context,
    build_flow_context,
    build_plan_summary,
    build_step_ref_mapping,
)
from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    mentions_form_field_needs,
    mentions_sectioned_form_intake,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    build_framework_guardrails_block,
    canonical_question_id,
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
    build_prompt_knowledge_sections,
)
from intric.flows.ai_builder.ai_builder_mcp_resources import (
    normalize_ai_builder_mcp_resources,
)
from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_confirmed_requirements_prompt_block,
    build_requirements_version,
    resolve_requirements_state,
)
from intric.flows.domain.flow import Flow

__all__ = [
    "build_available_kbs_context",
    "build_available_mcp_context",
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
    available_mcp_servers: list[dict[str, Any]] | None = None,
    attachment_context: str | None = None,
    planner_hints: str | None = None,
    planning_state_block: str | None = None,
    base_planning_state_version: int | None = None,
    ui_language: str | None = None,
    confirmed_requirements: dict[str, Any] | None = None,
    is_edit_mode: bool = False,
    unresolved_architectural_choices: frozenset[str] | None = None,
    action_policy: PlannerActionPolicy | None = None,
) -> str:
    """Build the complete system prompt for the AI builder LLM.

    Sections are injected conditionally based on conversation phase:
    - Discovery (no confirmed requirements): core + architecture only
    - Proposal (confirmed): core + recipes + contracts + anti-patterns
    - Edit mode: core + edit-specific knowledge, skip create-only content
    """
    sections = build_prompt_knowledge_sections(
        is_edit_mode=is_edit_mode,
        has_confirmed_requirements=confirmed_requirements is not None,
    )
    sections.insert(2, build_framework_guardrails_block())
    sections.insert(3, render_ask_question_vocabulary_block())
    if planning_state_block:
        sections.append(planning_state_block)
    if base_planning_state_version is not None:
        # The Utdataformat section in build_role_and_protocol tells the
        # model to copy `base_planning_state_version` from system context;
        # without this block the model has no source for the integer and
        # guesses, which terminally rejects as `version_mismatch`.
        sections.append(
            "## Session-version kontrakt\n\n"
            f"`base_planning_state_version` för denna tur = `{base_planning_state_version}`. "
            "Kopiera EXAKT detta värde in i "
            "`planning_state_delta.base_planning_state_version`."
        )

    if action_policy is not None:
        sections.append(render_action_policy_prompt_block(action_policy))
    elif unresolved_architectural_choices:
        # Server-side phase lock: when core architectural slots are still
        # unresolved, `commit_architecture` is rejected by the orchestrator.
        # Surfacing that contract in the prompt prevents the wasted LLM call
        # that a post-hoc rejection costs.
        slot_bullets = "\n".join(
            f"- `{slot}`" for slot in sorted(unresolved_architectural_choices)
        )
        sections.append(
            "## Tillåtna handlingar denna tur\n\n"
            "`commit_architecture` är **inte tillåtet** denna tur — följande "
            "arkitekturval är fortfarande oresolverade och måste klarna "
            "först:\n\n"
            f"{slot_bullets}\n\n"
            "Tillåtna handlingar denna tur: `ask_question`, "
            "`confirm_requirements`. Ställ en fråga som "
            "resolver en av ovanstående slots innan arkitekturen kan pinnas."
        )

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
            f"- ref=`{model['ref']}` | name=`{model.get('display_name', model['name'])}`"
            + f" | provider=`{model.get('provider', 'unknown')}`"
            for model in available_models
        )
        sections.append(
            "\n## Tillgängliga modeller\n\n"
            "Använd alltid det exakta `ref`-värdet i tool calls. `name` är bara läsbar etikett.\n\n"
            f"{model_lines}"
        )

    if available_knowledge_bases:
        kb_lines = "\n".join(
            f"- ref=`{kb['ref']}` | name=`{kb.get('display_name', kb['name'])}`"
            + (f" — {kb['description']}" if kb.get("description") else "")
            for kb in available_knowledge_bases
        )
        sections.append(
            "\n## Tillgängliga kunskapsbaser\n\n"
            "Använd alltid det exakta `ref`-värdet i tool calls. `name` är bara läsbar etikett.\n\n"
            f"{kb_lines}"
        )

    if available_mcp_servers:
        mcp_lines: list[str] = []
        for server in normalize_ai_builder_mcp_resources(available_mcp_servers):
            tool_parts = [_format_mcp_tool_for_prompt(tool) for tool in server["tools"]]
            tool_summary = "; tools=" + ", ".join(tool_parts) if tool_parts else ""
            mcp_lines.append(
                f"- server_ref=`{server['ref']}` | name=`{server['display_name']}`"
                f"{tool_summary}"
                + (f" — {server['description']}" if server["description"] else "")
            )
        sections.append(
            "\n## Tillgängliga MCP-verktyg\n\n"
            "Planeringsfasen får läsa denna MCP-metadata men ska inte köra MCP-verktyg. "
            "Verktygsbeskrivningar är beslutsstöd, inte användartillstånd. "
            "Använd MCP endast när användarens mål kräver externa verktyg eller levande data. "
            "Om målet verkar kräva extern åtkomst men systemval eller tillstånd saknas, "
            "ställ en kort förtydligande fråga innan du lägger till MCP-referenser. "
            "Använd `mcp_tool_refs` för minsta möjliga åtkomst; `mcp_server_refs` "
            "aktiverar serverns tillgängliga verktyg för just det steget. "
            "Kombinera inte MCP med `knowledge_refs` på samma steg.\n\n"
            f"{chr(10).join(mcp_lines)}"
        )

    if attachment_context:
        sections.append(attachment_context)

    if planner_hints:
        sections.append(f"\n## Planeringshintar\n\n{planner_hints}")

    if ui_language == "sv":
        sections.append(
            "\n## Aktivt gränssnittsspråk\n\n"
            "- All användarvänd text, alla strukturerade frågor, kravsammanfattningar och "
            "planförklaringar ska skrivas på svenska.\n"
            "- Blanda inte svenska och engelska i samma session.\n"
            "- Ge flödet ett kort, mänskligt namn med ord och mellanslag. Använd inte "
            "snake_case, interna mönster-id:n eller tekniska tokenkedjor som namn."
        )
    elif ui_language == "en":
        sections.append(
            "\n## Active UI language\n\n"
            "- All user-facing text, structured questions, requirements summaries, and plan "
            "explanations must be written in English.\n"
            "- Do not mix English and Swedish within the same session.\n"
            "- Give the flow a short human name with words and spaces. Do not use "
            "snake_case, internal pattern ids, or technical token chains as the name."
        )

    return "\n\n".join(sections)


def _format_mcp_tool_for_prompt(tool: Mapping[str, object]) -> str:
    display_name = str(tool["display_name"])
    ref = str(tool["ref"])
    description = str(tool.get("description") or "")
    label = f"{display_name} [{ref}]"
    if not description:
        return label
    return f"{label}: {_truncate_prompt_description(description)}"


def _truncate_prompt_description(description: str, *, limit: int = 180) -> str:
    compact = " ".join(description.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"


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
        for question_id in (_extract_question_id(message) for message in conversation)
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
    submission_tool = "edit_flow" if flow is not None else OUTLINE_FLOW_TOOL_NAME
    json_contract_term = "output_contract" if flow is not None else "output_fields"

    if _needs_pdf_scope_question(text, answered_ids):
        hints.append(
            f'- Frågegate: emittera `planner_action.kind="ask_question"` innan `{submission_tool}` för att avgöra '
            "om flödet ska stödja en PDF i taget eller flera dokument i samma körning. "
            'Använd `question_id="document_material_scope"` och formulera en enda textfråga i `payload.prompt` '
            "som beskriver valet mellan enkel- och fler-dokument-körning — inga extra payload-fält bortom "
            "`question_id`, `slot_name`, `prompt`."
        )

    if _needs_docx_mode_question(
        answered_ids,
        resolved_output=resolved_output,
        resolved_docx_mode=resolved_docx_mode,
    ):
        hints.append(
            f'- Frågegate: emittera `planner_action.kind="ask_question"` innan `{submission_tool}` för att avgöra '
            'hur DOCX-rapporten ska skapas. Använd `question_id="docx_output_mode"` och formulera en enda '
            "textfråga i `payload.prompt` som beskriver valet mellan mallbaserad DOCX och genererad DOCX "
            "utan mall — inga extra payload-fält bortom `question_id`, `slot_name`, `prompt`."
        )

    if (
        flow is not None
        and resolved_output in {"docx_document", "pdf_document"}
        and flow_defaults.get("final_output_mode")
        and resolved_output not in flow_defaults["final_output_mode"]
    ):
        hints.append(
            "- Edit-hint: om användaren bara byter slutformat ska upstream- och analyssteg lämnas oförändrade. "
            "Ändra dokumentformat eller `document_delivery_mode` bara på det terminala dokumentsteget, "
            "om inte användaren uttryckligen ber om en större omstrukturering."
        )

    if _needs_pdf_generation_mode_question(
        answered_ids,
        resolved_output=resolved_output,
        resolved_pdf_mode=resolved_pdf_mode,
    ):
        hints.append(
            f'- Frågegate: emittera `planner_action.kind="ask_question"` innan `{submission_tool}` för att avgöra '
            "om PDF-resultatet ska vara en vanlig genererad PDF eller om användaren egentligen "
            'efterfrågar en fast PDF-mall. Använd `question_id="pdf_generation_mode"` och formulera '
            "en enda textfråga i `payload.prompt` som är tydlig med att inbyggd mallfyllning bara "
            "stöds för DOCX/Word — inga extra payload-fält bortom `question_id`, `slot_name`, `prompt`."
        )

    if input_intent.primary_runtime_input in {
        "audio",
        "documents",
        "text_and_documents",
    }:
        if flow is None:
            hints.append(
                "- Implementationshint: eftersom användaren laddar upp PDF/dokument/filer vid körning ska "
                "outline-planen beskriva den semantiska bearbetningen från uppladdat material; backend "
                "härleder uppladdnings- och obligatoriskhetsmekanik för 'Ta emot filer vid körning' från "
                "den låsta arkitekturen."
            )
        else:
            hints.append(
                "- Implementationshint: eftersom användaren laddar upp PDF/dokument/filer vid körning ska "
                "relevanta `flow_input`-steg använda `input_config.runtime_input.enabled=true` "
                "så att 'Ta emot filer vid körning' aktiveras."
            )

    if input_intent.audio_requested:
        if flow is None:
            hints.append(
                "- Implementationshint: eftersom användaren nämner ljud/transkribering ska "
                'relevanta steg använda `input_type="audio"` och `output_type="text"`. '
                "Backend härleder sedan rätt transkriberingsläge."
            )
        else:
            hints.append(
                "- Implementationshint: eftersom användaren nämner ljud/transkribering ska "
                'nytillagda steg använda `input_type="audio"` och `output_type="text"`. '
                "Backend härleder då rätt transkriberingsläge för nya steg; patcha bara "
                "`output_mode` direkt om du uttryckligen behöver ändra ett befintligt steg."
            )

    if mentions_form_field_needs(text):
        hints.append(
            "- Designhint: eftersom användaren beskriver värden som ska anges eller väljas vid körning "
            "(t.ex. språk, fokus, datum, referensnummer eller nivå) ska dessa modelleras som "
            "`form_fields` så att senare steg kan använda dem som variabler."
        )

    if mentions_sectioned_form_intake(text):
        hints.append(
            "- Designhint: när användaren beskriver ett fast set rubriker/sektioner där användaren ska lämna fritext "
            "per sektion ska detta modelleras som `form_fields` (ett textfält per rubrik) i stället för ett eget "
            "insamlingssteg per sektion. Låt senare steg använda dessa fält via `uses_form_fields` och skapa sedan "
            "den slutliga sammanställningen från de insamlade fälten."
        )

    if _mentions_structured_extraction(text):
        hints.append(
            "- Designhint: om planen innehåller steg som ska extrahera namngivna fält, listor eller "
            'objekt för senare återanvändning ska dessa steg använda `output_type="json"` och tydliga '
            f"`{json_contract_term}`. Presentera inte ett JSON-steg utan strukturerad fältdefinition."
        )

    if should_prefer_structured_intermediate(
        text=intent_text,
        input_intent=input_intent,
        output_intent=output_intent,
        flow_defaults=flow_defaults,
        answers=answer_signals,
    ):
        hints.append(
            "- Designhint: eftersom behovet beskriver flera analyssteg och en strukturerad leverans "
            "bör planen använda mellanliggande JSON/strukturerad data där det förbättrar kvalitet "
            "och återanvändning mellan steg. Fråga inte användaren om detta som ett eget krav om "
            "slutresultatet inte ändras."
        )

    if resolved_docx_mode == "template_fill_docx":
        if flow is None:
            hints.append(
                "- Implementationshint: eftersom användaren nämner mallar/template_fill ska "
                'relevanta steg använda `document_delivery_mode="template_fill"` och '
                '`output_type="docx"`. Backend härleder sedan rätt output_mode. '
                "Användaren behöver koppla DOCX-mallen manuellt efter att flödet skapats."
            )
        else:
            hints.append(
                "- Implementationshint: eftersom användaren nämner mallar/template_fill ska "
                'nytillagda steg använda `document_delivery_mode="template_fill"` och '
                '`output_type="docx"`. Backend härleder rätt output_mode för nya steg. '
                "Användaren behöver koppla DOCX-mallen manuellt efter att flödet skapats."
            )

    if resolved_pdf_mode == "pdf_template_requested":
        hints.append(
            "- Designhint: användaren verkar efterfråga en fast PDF-mall. Modellera inte detta som "
            "DOCX-mallfyllning, eftersom native template filling bara stöds för DOCX/Word. Håll PDF-flödet "
            "ärligt som genererad PDF, eller be användaren byta till en DOCX-mall om exakt mallfyllning är avgörande."
        )
    elif resolved_output is None and _mentions_template_need(text):
        if flow is None:
            hints.append(
                "- Designhint: om användaren menar en Word-mall ska relevanta steg använda "
                '`document_delivery_mode="template_fill"` och `output_type="docx"`. '
                "Om användaren i stället menar en PDF-mall ska du först klargöra det via "
                "`pdf_generation_mode`."
            )
        else:
            hints.append(
                "- Designhint: om användaren menar en Word-mall ska relevanta steg använda "
                '`document_delivery_mode="template_fill"` och `output_type="docx"` för nya steg. '
                "Om användaren i stället menar en PDF-mall ska du först klargöra det via "
                "`pdf_generation_mode`."
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

    budget = (
        context_window - system_prompt_tokens - max_output_tokens - safety_buffer_tokens
    )
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
            while (
                tool_index < len(messages)
                and messages[tool_index].get("role") == "tool"
            ):
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
        for tool_call in cast(list[object], tool_calls):
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
    question_answer = question_answer_from_metadata(message.metadata)
    if question_answer is None:
        return None
    question_id = question_answer_question_id(question_answer)
    return canonical_question_id(question_id) if question_id is not None else None


def _needs_pdf_scope_question(text: str, answered_ids: set[str]) -> bool:
    if "document_material_scope" in answered_ids:
        return False
    mentions_documents = any(token in text for token in ("pdf", "dokument", "dokumen"))
    mentions_plurality = any(
        token in text
        for token in (
            "flera",
            "ett eller flera",
            "många",
            "samtidigt",
            "mellan dokument",
        )
    )
    mentions_comparison = any(
        token in text
        for token in ("jämför", "jämföra", "jämförelse", "motsägelser", "skillnader")
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
    return (
        resolved_output == "pdf_document"
        and resolved_pdf_mode == "pdf_template_requested"
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


def has_confirmed_requirements(conversation: list[ConversationMessage]) -> bool:
    """Check if the latest requirements summary is confirmed."""
    return resolve_requirements_state(conversation).confirmed
