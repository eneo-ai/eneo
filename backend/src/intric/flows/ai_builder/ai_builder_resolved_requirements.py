from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    has_explicit_structured_answer,
    resolve_output_intent,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_requirements_state import (
    RequirementsState,
    resolve_requirements_state,
)
from intric.flows.domain.flow import Flow

SlotSource = Literal[
    "structured_answer", "requirements_summary", "flow_default", "heuristic"
]


@dataclass(frozen=True, slots=True)
class RequirementSlot:
    name: str
    value: str
    source: SlotSource
    evidence: tuple[str, ...]
    confidence: Literal["high", "medium"]


@dataclass(frozen=True, slots=True)
class ResolvedRequirementsState:
    slots: tuple[RequirementSlot, ...]

    def slot(self, name: str) -> RequirementSlot | None:
        for slot in self.slots:
            if slot.name == name:
                return slot
        return None


def build_resolved_requirements_state(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
) -> ResolvedRequirementsState:
    answer_signals = extract_answer_signals(conversation)
    freeform_text = aggregate_freeform_user_text(conversation)
    flow_defaults = build_flow_discovery_defaults(flow)
    requirements_state = resolve_requirements_state(conversation)
    input_intent = resolve_input_intent(
        freeform_text,
        answer_signals,
        flow=flow,
    )
    output_intent = resolve_output_intent(
        freeform_text,
        answer_signals,
        flow_defaults=flow_defaults,
    )

    slots: list[RequirementSlot] = []

    primary_runtime_input = input_intent.primary_runtime_input
    if primary_runtime_input != "unknown":
        slots.append(
            _build_slot(
                name="primary_runtime_input",
                value=primary_runtime_input,
                question_id="input_material_mode",
                conversation=conversation,
                answer_signals=answer_signals,
                flow_defaults=flow_defaults,
                requirements_state=requirements_state,
                freeform_text=freeform_text,
                summary_field="input_description",
            )
        )

    if output_intent.terminal_output is not None:
        slots.append(
            _build_slot(
                name="terminal_output",
                value=output_intent.terminal_output,
                question_id="final_output_mode",
                conversation=conversation,
                answer_signals=answer_signals,
                flow_defaults=flow_defaults,
                requirements_state=requirements_state,
                freeform_text=freeform_text,
                summary_field="output_description",
            )
        )

    if output_intent.docx_output_mode is not None:
        slots.append(
            _build_slot(
                name="docx_output_mode",
                value=output_intent.docx_output_mode,
                question_id="docx_output_mode",
                conversation=conversation,
                answer_signals=answer_signals,
                flow_defaults=flow_defaults,
                requirements_state=requirements_state,
                freeform_text=freeform_text,
                summary_field="output_description",
            )
        )

    if output_intent.pdf_generation_mode is not None:
        slots.append(
            _build_slot(
                name="pdf_generation_mode",
                value=output_intent.pdf_generation_mode,
                question_id="pdf_generation_mode",
                conversation=conversation,
                answer_signals=answer_signals,
                flow_defaults=flow_defaults,
                requirements_state=requirements_state,
                freeform_text=freeform_text,
                summary_field="output_description",
            )
        )

    return ResolvedRequirementsState(slots=tuple(slots))


def build_resolved_requirements_prompt_block(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
) -> str | None:
    state = build_resolved_requirements_state(conversation, flow=flow)
    if not state.slots:
        return None

    lines = [
        "## Backend-resolved requirements state",
        "",
        "Use these backend-grounded slots before re-reading the raw transcript. Structured answers and confirmed summaries should outweigh weaker heuristic inference.",
        "",
    ]
    for slot in state.slots:
        evidence = "; ".join(slot.evidence)
        lines.append(
            f"- {slot.name}: {slot.value} (source={slot.source}, confidence={slot.confidence}, evidence={evidence})"
        )
    return "\n".join(lines)


def _build_slot(
    *,
    name: str,
    value: str,
    question_id: str,
    conversation: list[ConversationMessage],
    answer_signals: dict[str, set[str]],
    flow_defaults: dict[str, set[str]],
    requirements_state: RequirementsState,
    freeform_text: str,
    summary_field: Literal["input_description", "output_description"],
) -> RequirementSlot:
    source, evidence, confidence = _resolve_slot_origin(
        question_id=question_id,
        conversation=conversation,
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        requirements_state=requirements_state,
        freeform_text=freeform_text,
        summary_field=summary_field,
    )
    return RequirementSlot(
        name=name,
        value=value,
        source=source,
        evidence=evidence,
        confidence=confidence,
    )


def _resolve_slot_origin(
    *,
    question_id: str,
    conversation: list[ConversationMessage],
    answer_signals: dict[str, set[str]],
    flow_defaults: dict[str, set[str]],
    requirements_state: RequirementsState,
    freeform_text: str,
    summary_field: Literal["input_description", "output_description"],
) -> tuple[SlotSource, tuple[str, ...], Literal["high", "medium"]]:
    if has_explicit_structured_answer(conversation, question_id):
        return (
            "structured_answer",
            (f"question_answer:{question_id}",),
            "high",
        )

    latest_summary = requirements_state.latest_summary
    if latest_summary is not None:
        summary_value = getattr(latest_summary, summary_field)
        if isinstance(summary_value, str) and summary_value:
            return (
                "requirements_summary",
                (f"requirements_summary.{summary_field}={summary_value}",),
                "high",
            )

    if flow_defaults.get(question_id):
        return (
            "flow_default",
            (f"flow_default:{question_id}",),
            "high",
        )

    if answer_signals.get(question_id):
        return (
            "structured_answer",
            (f"answer_signal:{question_id}",),
            "high",
        )

    heuristic_evidence = (
        "heuristic:role-aware freeform analysis"
        if freeform_text
        else "heuristic:no explicit evidence"
    )
    return ("heuristic", (heuristic_evidence,), "medium")
