"""Derive `PlanningState` from a conversation and render the planner
prompt block from it.

This module owns the deterministic path from a raw conversation to a
stamped `PlanningState` and from that state to the prompt block the
planner LLM reads.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    has_explicit_docx_mode_text,
    has_explicit_pdf_mode_text,
    has_explicit_structured_answer,
    mentions_runtime_metadata,
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
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    SlotClassificationResult,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
    NON_LLM_RESOLVABLE_SLOT_NAMES,
)
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    EvidenceRef,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
)
from intric.flows.ai_builder.question_catalog import legal_slot_values
from intric.flows.domain.flow import Flow


@dataclass(frozen=True, slots=True)
class _PolicyDefaultRule:
    default_value: str
    has_explicit_text: Callable[[str], bool]


def _never_explicit_text(_: str) -> bool:
    return False


_POLICY_DEFAULT_RULES: dict[str, _PolicyDefaultRule] = {
    "document_material_scope": _PolicyDefaultRule(
        default_value="flexible_document_case",
        has_explicit_text=_never_explicit_text,
    ),
    "runtime_metadata_fields": _PolicyDefaultRule(
        default_value="no_extra_metadata",
        has_explicit_text=mentions_runtime_metadata,
    ),
    "docx_output_mode": _PolicyDefaultRule(
        default_value="generated_docx",
        has_explicit_text=has_explicit_docx_mode_text,
    ),
    "pdf_generation_mode": _PolicyDefaultRule(
        default_value="generated_pdf",
        has_explicit_text=has_explicit_pdf_mode_text,
    ),
}


def build_planning_state_from_conversation(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
) -> PlanningState:
    """Derive a `PlanningState` from a conversation and optional `Flow`.

    Phase shifts to `discovering` once any slot resolves; otherwise the
    state stays at `awaiting_input`. Evidence captures the stable
    conversation message ids so the snapshot survives conversation
    compaction. Signals, architecture commit, and open questions are
    populated by later planner turns — this function seeds the
    deterministic slot surface only.
    """
    resolved_slots = _resolve_slots(conversation, flow=flow)
    phase = "discovering" if resolved_slots else "awaiting_input"
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase=phase,
        evidence=EvidenceRef(
            conversation_message_ids=[message.message_id for message in conversation],
        ),
        resolved_slots=resolved_slots,
    )


# PlanningPhase advance order. Stored as a tuple (not a dict with a get-default)
# so adding a new PlanningPhase Literal without updating this tuple raises
# ValueError on .index() instead of silently ranking the unknown phase at 0 —
# preservation must never silently degrade when the state machine grows.
_PHASE_ORDER: tuple[str, ...] = (
    "awaiting_input",
    "discovering",
    "ready_to_commit",
    "plan_proposed",
)

_MODEL_PROTECTED_SOURCES: frozenset[SlotSource] = frozenset(
    {"structured_answer", "requirements_summary", "flow_default"}
)


def carry_forward_persisted_planner_state(
    rebuilt: PlanningState,
    persisted: PlanningState | None,
) -> None:
    """Carry forward planner-owned fields from the previously persisted
    state onto a freshly rebuilt state — mutation-only, no return.

    `build_planning_state_from_conversation` reseeds only the
    deterministic slot surface. Planner-owned fields
    (`architecture_commit`, `draft_plan_id`) and phase transitions past
    `discovering` are written by explicit planner actions on prior
    turns. Without preservation, every later `commit_turn` or proposal
    save would erase them by overwrite. The caller still owns explicit
    replacement: if the current turn sets any of these fields on
    `rebuilt` before calling this helper, the persisted value is not
    copied over it.

    Phase is monotonic — if persisted advanced past what the rebuild
    derived, the advanced phase is preserved.
    """
    if persisted is None:
        return
    if (
        rebuilt.architecture_commit is None
        and persisted.architecture_commit is not None
    ):
        rebuilt.architecture_commit = persisted.architecture_commit
    if rebuilt.draft_plan_id is None and persisted.draft_plan_id is not None:
        rebuilt.draft_plan_id = persisted.draft_plan_id
    if _PHASE_ORDER.index(rebuilt.phase) < _PHASE_ORDER.index(persisted.phase):
        rebuilt.phase = persisted.phase


def merge_llm_resolved_slots(
    state: PlanningState,
    classification_result: SlotClassificationResult,
    *,
    prompt_hash: str,
) -> None:
    """Overlay model slots without displacing explicit user or flow evidence."""
    if not prompt_hash.strip():
        raise ValueError("prompt_hash must be non-empty")

    for classified_slot in classification_result.slots:
        if not _model_slot_is_persistable(classified_slot.slot_name):
            continue
        if (
            classified_slot.value == UNKNOWN_SLOT_VALUE
            or classified_slot.confidence == "low"
        ):
            continue
        if classified_slot.value not in legal_slot_values(classified_slot.slot_name):
            continue

        existing_slot = state.resolved_slots.get(classified_slot.slot_name)
        if not _model_slot_can_replace(
            existing_slot=existing_slot,
            model_confidence=classified_slot.confidence,
        ):
            continue

        state.resolved_slots[classified_slot.slot_name] = ResolvedSlot(
            name=classified_slot.slot_name,
            value=classified_slot.value,
            source="model",
            evidence=[
                f"model:{classified_slot.slot_name}:{prompt_hash}",
            ],
            confidence=classified_slot.confidence,
        )

    if state.resolved_slots and state.phase == "awaiting_input":
        state.phase = "discovering"


def _model_slot_is_persistable(slot_name: str) -> bool:
    return (
        slot_name in KNOWN_REQUIREMENT_SLOT_NAMES
        and slot_name not in NON_LLM_RESOLVABLE_SLOT_NAMES
    )


def _model_slot_can_replace(
    *,
    existing_slot: ResolvedSlot | None,
    model_confidence: SlotConfidence,
) -> bool:
    if existing_slot is None:
        return model_confidence in {"high", "medium"}
    if existing_slot.source in _MODEL_PROTECTED_SOURCES:
        return False
    if existing_slot.source == "policy_default":
        return model_confidence == "high"
    if existing_slot.source == "heuristic":
        if (
            existing_slot.name == "primary_runtime_input"
            and existing_slot.confidence == "high"
        ):
            return False
        return model_confidence in {"high", "medium"}
    return False


def _resolve_slots(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None,
) -> dict[str, ResolvedSlot]:
    answer_signals = extract_answer_signals(conversation)
    requirements_state = resolve_requirements_state(conversation)
    freeform_text = _semantic_planning_text(
        aggregate_freeform_user_text(conversation),
        requirements_state,
    )
    flow_defaults = build_flow_discovery_defaults(flow)
    input_intent = resolve_input_intent(freeform_text, answer_signals, flow=flow)
    output_intent = resolve_output_intent(
        freeform_text,
        answer_signals,
        flow_defaults=flow_defaults,
    )

    slots: dict[str, ResolvedSlot] = {}

    primary_runtime_input = input_intent.primary_runtime_input
    if primary_runtime_input != "unknown":
        slots["primary_runtime_input"] = _build_slot(
            name="primary_runtime_input",
            value=primary_runtime_input,
            question_id="input_material_mode",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field="input_description",
            slot_value=primary_runtime_input,
        )

    if output_intent.terminal_output is not None:
        slots["terminal_output"] = _build_slot(
            name="terminal_output",
            value=output_intent.terminal_output,
            question_id="final_output_mode",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field="output_description",
            slot_value=output_intent.terminal_output,
        )

    if output_intent.docx_output_mode is not None:
        slots["docx_output_mode"] = _build_slot(
            name="docx_output_mode",
            value=output_intent.docx_output_mode,
            question_id="docx_output_mode",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field="output_description",
            slot_value=output_intent.docx_output_mode,
        )

    if output_intent.pdf_generation_mode is not None:
        slots["pdf_generation_mode"] = _build_slot(
            name="pdf_generation_mode",
            value=output_intent.pdf_generation_mode,
            question_id="pdf_generation_mode",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field="output_description",
            slot_value=output_intent.pdf_generation_mode,
        )

    document_material_scope = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        question_id="document_material_scope",
    )
    if document_material_scope is None and primary_runtime_input in {
        "documents",
        "text_and_documents",
    }:
        document_material_scope = "flexible_document_case"
    if document_material_scope is not None:
        slots["document_material_scope"] = _build_slot(
            name="document_material_scope",
            value=document_material_scope,
            question_id="document_material_scope",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field=None,
            slot_value=document_material_scope,
        )

    # No policy default: ambiguous comparison prompts must ask for architecture.
    comparison_scope = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        question_id="comparison_scope",
    )
    if comparison_scope is not None:
        slots["comparison_scope"] = _build_slot(
            name="comparison_scope",
            value=comparison_scope,
            question_id="comparison_scope",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field=None,
            slot_value=comparison_scope,
        )

    structured_analysis_need = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        question_id="structured_analysis_need",
    )
    if structured_analysis_need is not None:
        slots["structured_analysis_need"] = _build_slot(
            name="structured_analysis_need",
            value=structured_analysis_need,
            question_id="structured_analysis_need",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field=None,
            slot_value=structured_analysis_need,
        )

    runtime_metadata_fields = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        question_id="runtime_metadata_fields",
    )
    if (
        runtime_metadata_fields is None
        and primary_runtime_input != "unknown"
        and not mentions_runtime_metadata(freeform_text)
    ):
        runtime_metadata_fields = "no_extra_metadata"
    if runtime_metadata_fields is not None:
        slots["runtime_metadata_fields"] = _build_slot(
            name="runtime_metadata_fields",
            value=runtime_metadata_fields,
            question_id="runtime_metadata_fields",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field=None,
            slot_value=runtime_metadata_fields,
        )

    return slots


def _semantic_planning_text(
    freeform_text: str,
    requirements_state: RequirementsState,
) -> str:
    latest_summary = requirements_state.latest_summary
    if latest_summary is None:
        return freeform_text
    summary_parts = (
        latest_summary.input_description,
        latest_summary.output_description,
        latest_summary.summary,
    )
    summary_text = " ".join(part for part in summary_parts if part)
    return " ".join(part for part in (freeform_text, summary_text) if part)


def _build_slot(
    *,
    name: str,
    value: str,
    question_id: str,
    conversation: list[ConversationMessage],
    flow_defaults: dict[str, set[str]],
    requirements_state: RequirementsState,
    freeform_text: str,
    summary_field: Literal["input_description", "output_description"] | None,
    slot_value: str,
) -> ResolvedSlot:
    source, evidence, confidence = _resolve_slot_origin(
        question_id=question_id,
        conversation=conversation,
        flow_defaults=flow_defaults,
        requirements_state=requirements_state,
        freeform_text=freeform_text,
        summary_field=summary_field,
        slot_value=slot_value,
    )
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=list(evidence),
        confidence=confidence,
    )


def _resolve_slot_origin(
    *,
    question_id: str,
    conversation: list[ConversationMessage],
    flow_defaults: dict[str, set[str]],
    requirements_state: RequirementsState,
    freeform_text: str,
    summary_field: Literal["input_description", "output_description"] | None,
    slot_value: str,
) -> tuple[SlotSource, tuple[str, ...], SlotConfidence]:
    if has_explicit_structured_answer(conversation, question_id):
        return (
            "structured_answer",
            (f"question_answer:{question_id}",),
            "high",
        )

    latest_summary = requirements_state.latest_summary
    if latest_summary is not None and summary_field is not None:
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

    if _is_policy_default_slot(
        question_id=question_id,
        slot_value=slot_value,
        freeform_text=freeform_text,
    ):
        return (
            "policy_default",
            (f"policy_default:{question_id}={slot_value}",),
            "medium",
        )

    heuristic_evidence = (
        "heuristic:role-aware freeform analysis"
        if freeform_text
        else "heuristic:no explicit evidence"
    )
    return (
        "heuristic",
        (heuristic_evidence,),
        _heuristic_slot_confidence(
            question_id=question_id,
            slot_value=slot_value,
            freeform_text=freeform_text,
        ),
    )


def _heuristic_slot_confidence(
    *,
    question_id: str,
    slot_value: str,
    freeform_text: str,
) -> SlotConfidence:
    if question_id != "input_material_mode" or not freeform_text:
        return "medium"

    input_intent = resolve_input_intent(freeform_text, {})
    if (
        input_intent.primary_runtime_input != slot_value
        or input_intent.needs_architecture_clarification
    ):
        return "medium"

    if slot_value == "audio":
        return (
            "high"
            if input_intent.audio_requested
            and not input_intent.document_runtime_input_requested
            else "medium"
        )
    if slot_value in {"documents", "text_and_documents"}:
        return (
            "high"
            if input_intent.document_runtime_input_requested
            and not input_intent.audio_requested
            else "medium"
        )
    if slot_value == "text":
        return "high"
    return "medium"


def _is_policy_default_slot(
    *,
    question_id: str,
    slot_value: str,
    freeform_text: str,
) -> bool:
    rule = _POLICY_DEFAULT_RULES.get(question_id)
    return (
        rule is not None
        and slot_value == rule.default_value
        and not rule.has_explicit_text(freeform_text)
    )


def _single_slot_value(
    *,
    answer_signals: dict[str, set[str]],
    flow_defaults: dict[str, set[str]],
    question_id: str,
) -> str | None:
    values = answer_signals.get(question_id) or flow_defaults.get(question_id)
    if not values or len(values) != 1:
        return None
    return next(iter(values))
