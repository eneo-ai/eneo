"""Derive `PlanningState` from persisted conversation facts.

This module owns the deterministic path from a compacted conversation
to a stamped `PlanningState`. Planner prompt rendering lives elsewhere;
this layer only resolves durable slots, result signals, schema evidence,
and committed architecture state.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

from eneo.flows.ai_builder.ai_builder_canonicalization import (
    canonical_option_id,
    canonical_question_id,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    question_answer_from_metadata,
    question_answer_question_id,
    question_answer_values,
    slot_classification_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from eneo.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_answer_signals_from_text,
    infer_post_processing_goal,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    has_explicit_docx_mode_text,
    has_explicit_pdf_mode_text,
    has_explicit_structured_answer,
    mentions_runtime_metadata,
    resolve_output_intent,
    slot_names_blocked_by_explicit_uncertainty,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    RequirementsState,
    resolve_requirements_state,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    RESULT_OBLIGATION_SIGNAL_ID,
    RESULT_OBLIGATION_VALUES,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    NO_EXTRA_RUNTIME_METADATA,
    infer_runtime_metadata_slot,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    LLM_RESOLVABLE_SLOT_NAMES,
)
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    OutputSchemaEvidence,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
)
from eneo.flows.ai_builder.question_catalog import legal_slot_values
from eneo.flows.domain.flow import Flow
from eneo.flows.output_processing import (
    schema_yields_top_level_object,
    validate_schema_syntax,
)
from eneo.json_types import JsonObject
from eneo.main.exceptions import TypedIOValidationException


@dataclass(frozen=True, slots=True)
class _PolicyDefaultRule:
    default_value: str
    has_explicit_text: Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class _ModelValueAcceptancePolicy:
    requires_text_evidence: Callable[[str], bool]
    dependent_model_values: tuple[tuple[str, str], ...] = ()


def _never_explicit_text(_: str) -> bool:
    return False


def _text_evidences_stop_after_primary_operation(text: str) -> bool:
    return infer_post_processing_goal(text) == "stop_after_primary_operation"


def _text_evidences_structure_key_information(text: str) -> bool:
    return infer_post_processing_goal(text) == "structure_key_information"


_MODEL_VALUE_ACCEPTANCE_POLICIES: dict[tuple[str, str], _ModelValueAcceptancePolicy] = {
    # Register model values that need explicit user-text evidence before they
    # can become settled requirements; list values to drop with them as dependents.
    (
        "post_processing_goal",
        "stop_after_primary_operation",
    ): _ModelValueAcceptancePolicy(
        requires_text_evidence=_text_evidences_stop_after_primary_operation,
        dependent_model_values=(("structured_analysis_need", "text_only_analysis"),),
    ),
    (
        "post_processing_goal",
        "structure_key_information",
    ): _ModelValueAcceptancePolicy(
        requires_text_evidence=_text_evidences_structure_key_information,
    ),
}


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

_STRUCTURE_PROMOTING_POST_PROCESSING_GOALS: frozenset[str] = frozenset(
    {
        "action_followup",
        "compare_or_validate",
        "decision_support",
        "extract_key_information",
        "risk_or_issue_review",
        "structure_key_information",
    }
)

_FENCED_JSON_BLOCK_RE = re.compile(
    r"```(?:json|jsonschema|schema)?\s*(.*?)```",
    re.IGNORECASE | re.DOTALL,
)
_JSON_SCHEMA_SHAPE_KEYS = frozenset(
    {
        "$schema",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "allOf",
        "anyOf",
        "oneOf",
    }
)
_OUTPUT_SCHEMA_LABELS = (
    "output schema",
    "output json schema",
    "json output schema",
    "result schema",
    "response schema",
    "schema för utdata",
    "schema för resultat",
    "utdata schema",
    "utdataschema",
    "resultatschema",
    "output-schemat",
    "utdata-schemat",
)
_OUTPUT_SCHEMA_PROMOTABLE_TERMINAL_OUTPUT_SOURCES: frozenset[SlotSource] = frozenset(
    {
        "requirements_summary",
        "flow_default",
        "policy_default",
        "heuristic",
        "model",
    }
)


def build_planning_state_from_conversation(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
) -> PlanningState:
    """Derive a `PlanningState` from a conversation and optional `Flow`.

    Signals and architecture commit are populated by later planner turns;
    this function seeds the deterministic slot surface from the compacted
    conversation that was actually persisted.
    """
    output_schema_evidence = _derive_output_schema_evidence(conversation)
    resolved_slots = _resolve_slots(
        conversation,
        flow=flow,
        output_schema_evidence_present=output_schema_evidence is not None,
    )
    state = PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        resolved_slots=resolved_slots,
        output_schema_evidence=output_schema_evidence,
    )
    _replay_slot_classification_metadata(state, conversation, flow=flow)
    _reconcile_output_schema_evidence(state, conversation)
    return state


def _replay_slot_classification_metadata(
    state: PlanningState,
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None,
) -> None:
    """Replay persisted classifier facts and only then apply derived defaults."""
    freeform_text = aggregate_freeform_user_text(conversation)
    model_blocked_slots = slot_names_blocked_by_explicit_uncertainty(
        conversation,
        flow=flow,
    )
    replayed = False
    for message in conversation:
        classification = slot_classification_from_metadata(message.metadata)
        if classification is None:
            continue
        merge_llm_resolved_slots(
            state,
            classification.to_result(),
            prompt_hash=classification.prompt_hash,
            freeform_text=freeform_text,
            model_blocked_slots=model_blocked_slots,
        )
        replayed = True
    if replayed:
        apply_policy_defaults_from_resolved_slots(state, freeform_text=freeform_text)


_MODEL_PROTECTED_SOURCES: frozenset[SlotSource] = frozenset(
    {"structured_answer", "flow_default"}
)


def carry_forward_persisted_planner_state(
    rebuilt: PlanningState,
    persisted: PlanningState | None,
) -> None:
    """Carry forward planner-owned fields from the previously persisted
    state onto a freshly rebuilt state — mutation-only, no return.

    `build_planning_state_from_conversation` reseeds only the
    deterministic slot surface. Planner-owned `architecture_commit` is
    written by explicit planner actions on prior turns. Without
    preservation, every later `commit_turn` or proposal save would erase it
    by overwrite. The caller still owns explicit replacement: if the current
    turn sets this field on `rebuilt` before calling this helper, the
    persisted value is not copied over it.
    """
    if persisted is None:
        return
    if (
        rebuilt.architecture_commit is None
        and persisted.architecture_commit is not None
    ):
        rebuilt.architecture_commit = persisted.architecture_commit
    if (
        rebuilt.output_schema_evidence is None
        and persisted.output_schema_evidence is not None
    ):
        rebuilt.output_schema_evidence = persisted.output_schema_evidence
    current_file_ids = {item.file_id for item in rebuilt.file_roles}
    for file_role in persisted.file_roles:
        if file_role.file_id not in current_file_ids:
            rebuilt.file_roles.append(file_role)
            current_file_ids.add(file_role.file_id)


def _derive_output_schema_evidence(
    conversation: list[ConversationMessage],
) -> OutputSchemaEvidence | None:
    evidence: OutputSchemaEvidence | None = None
    for message in conversation:
        if message.role != "user" or not message.content:
            continue
        for match in _FENCED_JSON_BLOCK_RE.finditer(message.content):
            if not _mentions_output_schema_near_fence(message.content, match):
                continue
            schema = _parse_output_schema_candidate(match.group(1))
            if schema is None:
                continue
            evidence = OutputSchemaEvidence(
                json_schema=schema,
                source="freeform_text",
                confidence="high",
                evidence=[f"message:{message.message_id}", "fenced_json_schema"],
            )
    return evidence


def _reconcile_output_schema_evidence(
    state: PlanningState,
    conversation: list[ConversationMessage],
) -> None:
    evidence = state.output_schema_evidence
    if evidence is None:
        return

    terminal_output = state.resolved_slots.get("terminal_output")
    if terminal_output is not None and terminal_output.value == "structured_json":
        if terminal_output.source != "structured_answer":
            state.resolved_slots["terminal_output"] = (
                _output_schema_evidence_terminal_output_slot(evidence)
            )
        return

    schema_message_index = _latest_output_schema_evidence_message_index(conversation)
    if (
        terminal_output is not None
        and terminal_output.source == "structured_answer"
        and terminal_output.value != "structured_json"
    ):
        if _latest_non_json_output_answer_index(conversation) > schema_message_index:
            state.output_schema_evidence = None
        else:
            state.resolved_slots.pop("terminal_output", None)
        return

    if terminal_output is not None and (
        terminal_output.source not in _OUTPUT_SCHEMA_PROMOTABLE_TERMINAL_OUTPUT_SOURCES
    ):
        return
    if terminal_output is not None and terminal_output.value != "structured_text":
        state.resolved_slots.pop("terminal_output", None)
        return

    state.resolved_slots["terminal_output"] = (
        _output_schema_evidence_terminal_output_slot(evidence)
    )


def _output_schema_evidence_terminal_output_slot(
    evidence: OutputSchemaEvidence,
) -> ResolvedSlot:
    return ResolvedSlot(
        name="terminal_output",
        value="structured_json",
        source="heuristic",
        evidence=[
            "output_schema_evidence:fenced_json_schema",
            *evidence.evidence,
        ],
        confidence="high",
    )


def _latest_output_schema_evidence_message_index(
    conversation: list[ConversationMessage],
) -> int:
    index = -1
    for message_index, message in enumerate(conversation):
        if message.role != "user" or not message.content:
            continue
        for match in _FENCED_JSON_BLOCK_RE.finditer(message.content):
            if not _mentions_output_schema_near_fence(message.content, match):
                continue
            if _parse_output_schema_candidate(match.group(1)) is not None:
                index = message_index
    return index


def _latest_non_json_output_answer_index(
    conversation: list[ConversationMessage],
) -> int:
    index = -1
    for message_index, message in enumerate(conversation):
        if message.role != "user":
            continue
        answer = question_answer_from_metadata(message.metadata)
        if answer is None:
            continue
        question_id = question_answer_question_id(answer)
        if question_id is None:
            continue
        if canonical_question_id(question_id) != "terminal_output":
            continue
        values = {
            canonical_option_id("terminal_output", value)
            for value in question_answer_values(answer)
        }
        if values and "structured_json" not in values:
            index = message_index
    return index


def _mentions_output_schema_near_fence(
    content: str,
    match: re.Match[str],
) -> bool:
    # Labels usually sit immediately before the fence; keep the window local
    # so unrelated earlier schema talk does not claim a later JSON example.
    start = max(0, match.start() - 240)
    end = min(len(content), match.end() + 80)
    window = content[start:end].casefold()
    return any(label in window for label in _OUTPUT_SCHEMA_LABELS)


def _parse_output_schema_candidate(raw_json: str) -> JsonObject | None:
    try:
        parsed: object = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    # `json.loads` object keys are strings; the cast preserves the shared JSON alias.
    candidate = cast(JsonObject, parsed)
    if not _looks_like_json_schema(candidate):
        return None
    try:
        validate_schema_syntax(candidate, label="output_schema_evidence")
    except TypedIOValidationException:
        return None
    if not schema_yields_top_level_object(candidate):
        return None
    return candidate


def _looks_like_json_schema(candidate: JsonObject) -> bool:
    return any(key in candidate for key in _JSON_SCHEMA_SHAPE_KEYS)


def merge_llm_resolved_slots(
    state: PlanningState,
    classification_result: SlotClassificationResult,
    *,
    prompt_hash: str,
    freeform_text: str,
    model_blocked_slots: frozenset[str] = frozenset(),
) -> None:
    """Overlay model slots without displacing explicit user or flow evidence."""
    if not prompt_hash.strip():
        raise ValueError("prompt_hash must be non-empty")

    apply_model_blocked_slots(state, model_blocked_slots=model_blocked_slots)
    blocked_model_values = _blocked_model_values(
        classification_result=classification_result,
        freeform_text=freeform_text,
    )
    _merge_model_result_obligations(
        state,
        classification_result=classification_result,
        prompt_hash=prompt_hash,
    )

    for classified_slot in classification_result.slots:
        if not _model_slot_is_persistable(classified_slot.slot_name):
            continue
        if classified_slot.slot_name in model_blocked_slots:
            _clear_nonprotected_model_slot(state, classified_slot.slot_name)
            continue
        if (classified_slot.slot_name, classified_slot.value) in blocked_model_values:
            _clear_nonprotected_model_slot(state, classified_slot.slot_name)
            continue
        if classified_slot.value == UNKNOWN_SLOT_VALUE:
            _clear_nonprotected_model_slot(state, classified_slot.slot_name)
            continue
        if classified_slot.confidence == "low":
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


def _merge_model_result_obligations(
    state: PlanningState,
    *,
    classification_result: SlotClassificationResult,
    prompt_hash: str,
) -> None:
    legal_values = set(RESULT_OBLIGATION_VALUES)
    existing = {
        signal.value
        for signal in state.signals
        if signal.question_id == RESULT_OBLIGATION_SIGNAL_ID
    }
    for obligation in classification_result.secondary_obligations:
        if obligation not in legal_values or obligation in existing:
            continue
        state.signals.append(
            PlanningSignal(
                question_id=RESULT_OBLIGATION_SIGNAL_ID,
                value=obligation,
                confidence="high",
                source="model",
                provenance=[f"model:{RESULT_OBLIGATION_SIGNAL_ID}:{prompt_hash}"],
            )
        )
        existing.add(obligation)


def _blocked_model_values(
    *,
    classification_result: SlotClassificationResult,
    freeform_text: str,
) -> frozenset[tuple[str, str]]:
    blocked: set[tuple[str, str]] = set()
    for classified_slot in classification_result.slots:
        key = (classified_slot.slot_name, classified_slot.value)
        policy = _MODEL_VALUE_ACCEPTANCE_POLICIES.get(key)
        if policy is None:
            continue
        if policy.requires_text_evidence(freeform_text):
            continue
        blocked.add(key)
        blocked.update(policy.dependent_model_values)
    return frozenset(blocked)


def apply_model_blocked_slots(
    state: PlanningState,
    *,
    model_blocked_slots: frozenset[str],
) -> None:
    """Remove transient model-owned slots that current user intent blocks."""
    for slot_name in model_blocked_slots:
        if _model_slot_is_persistable(slot_name):
            _clear_nonprotected_model_slot(state, slot_name)


def _clear_nonprotected_model_slot(state: PlanningState, slot_name: str) -> None:
    existing_slot = state.resolved_slots.get(slot_name)
    # Model uncertainty/blocking must not revoke explicit choices.
    if (
        existing_slot is not None
        and existing_slot.source not in _MODEL_PROTECTED_SOURCES
    ):
        state.resolved_slots.pop(slot_name, None)


def apply_policy_defaults_from_resolved_slots(
    state: PlanningState,
    *,
    freeform_text: str,
) -> None:
    primary_runtime_input = state.resolved_slots.get("primary_runtime_input")
    if primary_runtime_input is not None:
        if (
            "document_material_scope" not in state.resolved_slots
            and primary_runtime_input.value in {"documents", "text_and_documents"}
        ):
            state.resolved_slots["document_material_scope"] = ResolvedSlot(
                name="document_material_scope",
                value="flexible_document_case",
                source="policy_default",
                evidence=[
                    "policy_default:document_material_scope=flexible_document_case",
                ],
                confidence="medium",
            )
        if (
            "runtime_metadata_fields" not in state.resolved_slots
            and not mentions_runtime_metadata(freeform_text)
        ):
            state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="policy_default",
                evidence=[
                    "policy_default:runtime_metadata_fields=no_extra_metadata",
                ],
                confidence="medium",
            )

    terminal_output = state.resolved_slots.get("terminal_output")
    if terminal_output is not None:
        if (
            terminal_output.value == "docx_document"
            and "docx_output_mode" not in state.resolved_slots
            and not has_explicit_docx_mode_text(freeform_text)
        ):
            state.resolved_slots["docx_output_mode"] = ResolvedSlot(
                name="docx_output_mode",
                value="generated_docx",
                source="policy_default",
                evidence=["policy_default:docx_output_mode=generated_docx"],
                confidence="medium",
            )
        if (
            terminal_output.value == "pdf_document"
            and "pdf_generation_mode" not in state.resolved_slots
            and not has_explicit_pdf_mode_text(freeform_text)
        ):
            state.resolved_slots["pdf_generation_mode"] = ResolvedSlot(
                name="pdf_generation_mode",
                value="generated_pdf",
                source="policy_default",
                evidence=["policy_default:pdf_generation_mode=generated_pdf"],
                confidence="medium",
            )

    _apply_structured_analysis_default_from_post_processing_goal(state)


def _apply_structured_analysis_default_from_post_processing_goal(
    state: PlanningState,
) -> None:
    if "structured_analysis_need" in state.resolved_slots:
        return
    default_slot = _structured_analysis_default_slot_from_post_processing_goal(
        state.resolved_slots.get("post_processing_goal")
    )
    if default_slot is None:
        return
    state.resolved_slots["structured_analysis_need"] = default_slot


def llm_resolvable_slot_values_for_state(
    state: PlanningState,
) -> dict[str, frozenset[str]]:
    candidate_slots = {
        slot_name
        for slot_name in LLM_RESOLVABLE_SLOT_NAMES
        if _model_slot_is_relevant(slot_name=slot_name, state=state)
        if _model_slot_can_replace(
            existing_slot=state.resolved_slots.get(slot_name),
            model_confidence="high",
        )
    }
    return {
        slot_name: legal_slot_values(slot_name) for slot_name in sorted(candidate_slots)
    }


def _model_slot_is_persistable(slot_name: str) -> bool:
    return slot_name in LLM_RESOLVABLE_SLOT_NAMES


def _model_slot_is_relevant(*, slot_name: str, state: PlanningState) -> bool:
    if slot_name != "structured_io_contract":
        return True
    primary_runtime_input = state.resolved_slots.get("primary_runtime_input")
    terminal_output = state.resolved_slots.get("terminal_output")
    return (
        primary_runtime_input is not None
        and primary_runtime_input.value == "json"
        and terminal_output is not None
        and terminal_output.value == "structured_json"
    )


def _model_slot_can_replace(
    *,
    existing_slot: ResolvedSlot | None,
    model_confidence: SlotConfidence,
) -> bool:
    """Return whether model classification may write this slot.

    Earlier model-sourced slots intentionally anchor the conversation until
    explicit structured answers, flow defaults, or requirements summaries
    produce a different source. This avoids a later speculative classifier
    turn rewriting accepted model evidence without user-visible confirmation.
    """
    if existing_slot is None:
        return model_confidence in {"high", "medium"}
    if existing_slot.source in _MODEL_PROTECTED_SOURCES:
        return False
    if existing_slot.source == "requirements_summary":
        return model_confidence == "high"
    if existing_slot.source == "policy_default":
        if existing_slot.name == "structured_analysis_need":
            return False
        return model_confidence == "high"
    if existing_slot.source == "heuristic":
        if (
            existing_slot.name == "primary_runtime_input"
            and existing_slot.confidence == "high"
        ):
            return False
        if (
            existing_slot.name == "structured_analysis_need"
            and existing_slot.confidence == "high"
        ):
            return False
        if (
            existing_slot.name == "runtime_metadata_fields"
            and existing_slot.value == NO_EXTRA_RUNTIME_METADATA
            and existing_slot.confidence == "high"
        ):
            return False
        return model_confidence in {"high", "medium"}
    return False


def _resolve_slots(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None,
    output_schema_evidence_present: bool,
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
        conversation=conversation,
        output_schema_evidence_present=output_schema_evidence_present,
    )

    slots: dict[str, ResolvedSlot] = {}

    primary_runtime_input = input_intent.primary_runtime_input
    if primary_runtime_input != "unknown":
        slots["primary_runtime_input"] = _build_slot(
            name="primary_runtime_input",
            value=primary_runtime_input,
            question_id="primary_runtime_input",
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
            question_id="terminal_output",
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

    post_processing_goal = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        question_id="post_processing_goal",
    )
    if post_processing_goal is not None:
        slots["post_processing_goal"] = _build_slot(
            name="post_processing_goal",
            value=post_processing_goal,
            question_id="post_processing_goal",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field=None,
            slot_value=post_processing_goal,
        )

    structured_io_contract = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        question_id="structured_io_contract",
    )
    if structured_io_contract is not None:
        slots["structured_io_contract"] = _build_slot(
            name="structured_io_contract",
            value=structured_io_contract,
            question_id="structured_io_contract",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_state=requirements_state,
            freeform_text=freeform_text,
            summary_field=None,
            slot_value=structured_io_contract,
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
    else:
        structured_analysis_default_slot = (
            _structured_analysis_default_slot_from_post_processing_goal(
                slots.get("post_processing_goal")
            )
        )
        if structured_analysis_default_slot is not None:
            slots["structured_analysis_need"] = structured_analysis_default_slot

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

    flow_default_values = flow_defaults.get(question_id, set())
    if slot_value in flow_default_values:
        return (
            "flow_default",
            (f"flow_default:{question_id}",),
            "high",
        )

    latest_summary = requirements_state.latest_summary
    if latest_summary is not None and summary_field is not None:
        summary_value = getattr(latest_summary, summary_field)
        if (
            isinstance(summary_value, str)
            and summary_value
            and _requirements_summary_supports_slot(
                question_id=question_id,
                summary_value=summary_value,
                slot_value=slot_value,
            )
        ):
            return (
                "requirements_summary",
                (f"requirements_summary.{summary_field}={summary_value}",),
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


def _requirements_summary_supports_slot(
    *,
    question_id: str,
    summary_value: str,
    slot_value: str,
) -> bool:
    if question_id == "primary_runtime_input":
        return (
            resolve_input_intent(summary_value, {}).primary_runtime_input == slot_value
        )

    output_intent = resolve_output_intent(summary_value, {})
    if question_id == "terminal_output":
        return output_intent.terminal_output == slot_value
    if question_id == "docx_output_mode":
        return output_intent.docx_output_mode == slot_value
    if question_id == "pdf_generation_mode":
        return output_intent.pdf_generation_mode == slot_value
    return False


def _structured_analysis_default_for_post_processing_goal(
    post_processing_goal: str | None,
) -> str | None:
    if post_processing_goal in _STRUCTURE_PROMOTING_POST_PROCESSING_GOALS:
        return "use_structured_analysis"
    return None


def _structured_analysis_default_slot_from_post_processing_goal(
    post_processing_goal: ResolvedSlot | None,
) -> ResolvedSlot | None:
    if post_processing_goal is None:
        return None
    value = _structured_analysis_default_for_post_processing_goal(
        post_processing_goal.value
    )
    if value is None:
        return None
    return ResolvedSlot(
        name="structured_analysis_need",
        value=value,
        source="heuristic",
        evidence=[
            "heuristic:structured_analysis_need=post_processing_goal:"
            f"{post_processing_goal.value}",
            *post_processing_goal.evidence,
        ],
        confidence=post_processing_goal.confidence,
    )


def _heuristic_slot_confidence(
    *,
    question_id: str,
    slot_value: str,
    freeform_text: str,
) -> SlotConfidence:
    if question_id == "terminal_output":
        return _heuristic_terminal_output_confidence(slot_value, freeform_text)
    if question_id == "docx_output_mode":
        return _heuristic_docx_output_mode_confidence(slot_value, freeform_text)
    if question_id == "pdf_generation_mode":
        return _heuristic_pdf_generation_mode_confidence(slot_value, freeform_text)
    if question_id in {"document_material_scope", "comparison_scope"}:
        return _heuristic_text_signal_confidence(
            question_id=question_id,
            slot_value=slot_value,
            freeform_text=freeform_text,
        )
    if (
        question_id == "runtime_metadata_fields"
        and slot_value == NO_EXTRA_RUNTIME_METADATA
        and infer_runtime_metadata_slot(freeform_text) == NO_EXTRA_RUNTIME_METADATA
    ):
        return "high"
    if question_id == "post_processing_goal":
        return (
            "high"
            if infer_post_processing_goal(freeform_text) == slot_value
            else "medium"
        )
    if question_id != "primary_runtime_input" or not freeform_text:
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
    if slot_value == "json":
        return "high" if input_intent.primary_runtime_input == "json" else "medium"
    if slot_value == "text":
        return "high"
    return "medium"


def _heuristic_terminal_output_confidence(
    slot_value: str,
    freeform_text: str,
) -> SlotConfidence:
    if not freeform_text:
        return "medium"
    output_intent = resolve_output_intent(freeform_text, {})
    return "high" if output_intent.terminal_output == slot_value else "medium"


def _heuristic_docx_output_mode_confidence(
    slot_value: str,
    freeform_text: str,
) -> SlotConfidence:
    if not has_explicit_docx_mode_text(freeform_text):
        return "medium"
    output_intent = resolve_output_intent(freeform_text, {})
    return "high" if output_intent.docx_output_mode == slot_value else "medium"


def _heuristic_pdf_generation_mode_confidence(
    slot_value: str,
    freeform_text: str,
) -> SlotConfidence:
    if not has_explicit_pdf_mode_text(freeform_text):
        return "medium"
    output_intent = resolve_output_intent(freeform_text, {})
    return "high" if output_intent.pdf_generation_mode == slot_value else "medium"


def _heuristic_text_signal_confidence(
    *,
    question_id: str,
    slot_value: str,
    freeform_text: str,
) -> SlotConfidence:
    signals = infer_answer_signals_from_text(freeform_text)
    return "high" if signals.get(question_id) == {slot_value} else "medium"


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
