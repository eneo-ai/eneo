"""Derive `PlanningState` from persisted conversation facts.

This module owns the deterministic path from a compacted conversation
to a stamped `PlanningState`. Planner prompt rendering lives elsewhere;
this layer only resolves durable slots, result signals, schema evidence,
and committed architecture state.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_aggregation_intent import (
    comparison_scope_is_relevant,
    report_disposition_is_relevant,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    ClassifierRetentionClass,
    SlotClassificationNamedResultEvidenceMetadata,
    question_answer_from_metadata,
    slot_classification_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from eneo.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_answer_signals_from_text,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import RequirementsSummaryPayload
from eneo.flows.ai_builder.ai_builder_field_identity import fold_result_field_name
from eneo.flows.ai_builder.ai_builder_form_intake_signals import (
    FORM_INTAKE_NEEDS_FIELDS_SIGNAL,
    FORM_INTAKE_SIGNAL_ID,
    SECTIONED_FORM_INTAKE_SIGNAL,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_unprompted_user_text,
    extract_answer_signals,
    has_explicit_docx_mode_text,
    has_explicit_pdf_mode_text,
    has_explicit_structured_answer,
    resolve_output_intent,
    slot_names_blocked_by_explicit_uncertainty,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    AttestedDisclosure,
    RequirementsState,
    resolve_attested_disclosure,
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
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    build_schema_evidence,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    UNKNOWN_SLOT_VALUE,
    ClassifiedFileRole,
    ClassifiedFormIntake,
    ClassifiedNamedResultDelta,
    ClassifiedSlot,
    SlotClassificationResult,
    planning_reference_cites_source,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
    LLM_RESOLVABLE_SLOT_NAMES,
)
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    NAMED_RESULT_EVIDENCE_MAX_CITATIONS,
    NAMED_RESULT_EVIDENCE_MAX_ITEMS,
    PLANNER_CONTRACT_VERSION,
    TEMPLATE_PLACEHOLDER_EVIDENCE_PREFIX,
    TEMPLATE_PLACEHOLDER_SOURCE_EVIDENCE_SUFFIX,
    CheckpointIntent,
    ConfirmedRuntimeMetadataField,
    ExampleOutputConstraintEvidence,
    ExampleOutputSchemaInferenceOutcome,
    FileRole,
    FileRoleEvidence,
    MappedFileLimit,
    NamedResultDeclaredShape,
    NamedResultEvidence,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
    SchemaEvidence,
    SlotConfidence,
    SlotSource,
)
from eneo.flows.ai_builder.question_catalog import legal_slot_values
from eneo.flows.domain.flow import Flow
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    max_mapped_items_per_step,
)
from eneo.json_types import JsonObject


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
    "docx_output_mode": _PolicyDefaultRule(
        default_value="generated_docx",
        has_explicit_text=has_explicit_docx_mode_text,
    ),
    "pdf_generation_mode": _PolicyDefaultRule(
        default_value="generated_pdf",
        has_explicit_text=has_explicit_pdf_mode_text,
    ),
}

CLASSIFIER_REBUILD_INPUT_CLASSES: frozenset[ClassifierRetentionClass] = frozenset(
    {
        "slot",
        "file_role",
        "checkpoint_update",
        "form_intake",
        "named_result_evidence",
        "example_output_constraint",
        "schema_direction",
        "secondary_obligation",
    }
)


def build_planning_state_from_conversation(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    attachment_file_roles: list[FileRoleEvidence] | None = None,
    mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
) -> PlanningState:
    """Derive a `PlanningState` from a conversation and optional `Flow`.

    Signals and architecture commit are populated by later planner turns;
    this function seeds the deterministic slot surface from the compacted
    conversation that was actually persisted.
    """
    resolved_slots = _resolve_slots(conversation, flow=flow)
    state = PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        resolved_slots=resolved_slots,
        file_roles=list(attachment_file_roles or ()),
        input_fields=_confirmed_input_fields(conversation),
        mapped_file_limit=_mapped_file_limit(
            conversation,
            mapped_execution_policy=mapped_execution_policy,
        ),
    )
    _replay_slot_classification_metadata(state, conversation, flow=flow)
    _reconcile_report_disposition_after_classifier_replay(state, conversation)
    resolve_docx_mode_from_template_evidence(state)
    _reconcile_dependent_slot_relevance(state)
    # Acceptance is graded last, on the finished slot surface. The first pass
    # can only attribute a slot it was able to resolve, and a slot whose
    # relevance depends on classifier-owned facts is resolved above, after the
    # replay. Grading acceptance before that left the accepted value below
    # commit grade here while the acknowledgment turn — which starts from this
    # same state, already replayed — graded it above, and `commit_turn` then
    # refused the architecture the user had just confirmed.
    apply_attested_requirements(
        state,
        resolve_requirements_state(conversation).attested_summary,
    )
    return state


def _mapped_file_limit(
    conversation: list[ConversationMessage],
    *,
    mapped_execution_policy: FlowMappedExecutionPolicy | None,
) -> MappedFileLimit:
    # Propose the item ceiling the call ceiling can actually admit: runtime
    # admission reserves one native-JSON fallback call on top of per-item calls.
    proposed = (
        max_mapped_items_per_step(mapped_execution_policy)
        if mapped_execution_policy is not None
        else None
    )
    latest_answer = None
    for message in reversed(conversation):
        answer = question_answer_from_metadata(message.metadata)
        if answer is not None and answer.question_id == "mapped_file_limit":
            latest_answer = answer
            break
    if proposed is None:
        return MappedFileLimit(diagnostic="policy_unset")
    if latest_answer is None:
        # The shipped ceiling IS the answer — defaults exist to avoid
        # questions. Discovery asks only when an authored answer failed
        # (error diagnostics below); an unprompted default never blocks.
        return MappedFileLimit(
            proposed_value=proposed,
            accepted_value=proposed,
            provenance="policy_default",
        )
    custom = latest_answer.custom_value
    if custom is not None:
        normalized = custom.strip()
        try:
            accepted = int(normalized)
        except ValueError:
            return MappedFileLimit(
                proposed_value=proposed,
                diagnostic="not_an_integer",
            )
        if str(accepted) != normalized:
            return MappedFileLimit(
                proposed_value=proposed,
                diagnostic="not_an_integer",
            )
        if accepted < 1:
            return MappedFileLimit(proposed_value=proposed, diagnostic="not_positive")
        if accepted > proposed:
            return MappedFileLimit(proposed_value=proposed, diagnostic="exceeds_policy")
        return MappedFileLimit(
            proposed_value=proposed,
            accepted_value=accepted,
            provenance="authored",
        )
    if (
        latest_answer.selected_option_id == "organization_limit"
        or latest_answer.selected_value == "organization_limit"
    ):
        return MappedFileLimit(
            proposed_value=proposed,
            accepted_value=proposed,
            provenance="policy_default",
        )
    if (
        latest_answer.selected_option_id is None
        and latest_answer.selected_value is None
    ):
        # An answer carrying neither a selection nor a custom value is no
        # answer — the default applies as if never asked.
        return MappedFileLimit(
            proposed_value=proposed,
            accepted_value=proposed,
            provenance="policy_default",
        )
    return MappedFileLimit(
        proposed_value=proposed,
        diagnostic="confirmation_required",
    )


def _confirmed_input_fields(
    conversation: list[ConversationMessage],
) -> list[ConfirmedRuntimeMetadataField]:
    for message in reversed(conversation):
        answer = question_answer_from_metadata(message.metadata)
        if (
            answer is not None
            and answer.question_id == "runtime_metadata_field_details"
            and answer.input_fields is not None
        ):
            return [
                ConfirmedRuntimeMetadataField(
                    value=field.value,
                    purpose=field.purpose,
                    structured_answer_message_id=message.message_id,
                )
                for field in answer.input_fields
            ]
    return []


def _replay_slot_classification_metadata(
    state: PlanningState,
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None,
) -> None:
    """Replay persisted classifier facts and only then apply derived defaults."""
    freeform_text = aggregate_unprompted_user_text(conversation)
    model_blocked_slots = slot_names_blocked_by_explicit_uncertainty(
        conversation,
        flow=flow,
    )
    replayed = False
    for index, message in enumerate(conversation):
        classification = slot_classification_from_metadata(message.metadata)
        if classification is None or classification.outcome != "resolved":
            continue
        prompt_hash = classification.prompt_hash
        assert prompt_hash is not None
        classification_result = classification.to_result()
        merge_llm_resolved_slots(
            state,
            classification_result,
            prompt_hash=prompt_hash,
            freeform_text=freeform_text,
            model_blocked_slots=model_blocked_slots,
            settled_by_acceptance=attested_slots_without_newer_evidence(
                classification_result,
                conversation=conversation,
                cited_message_ids_by_source={
                    source.source_id: source.message_id
                    for source in classification.source_inventory
                },
                classified_at_index=index,
            ),
        )
        _apply_replayed_named_result_evidence(
            state,
            snapshot=classification.named_result_evidence,
        )
        replayed = True
    if replayed:
        apply_policy_defaults_from_resolved_slots(state, freeform_text=freeform_text)


def _reconcile_report_disposition_after_classifier_replay(
    state: PlanningState,
    conversation: list[ConversationMessage],
) -> None:
    """Apply an explicit report choice after its prerequisites are replayed.

    Report disposition is the only structured answer whose relevance depends on
    classifier-owned input cardinality. It cannot be resolved during the first
    deterministic pass when those facts exist only in persisted classifier
    metadata. Re-checking this one answer after replay lets explicit user intent
    outrank an older model inference without carrying unrelated slots forward.
    """
    if not has_explicit_structured_answer(conversation, "report_disposition"):
        return
    values = extract_answer_signals(conversation).get("report_disposition")
    if values is None or len(values) != 1:
        return
    value = next(iter(values))
    if value not in legal_slot_values("report_disposition"):
        return
    if not _report_disposition_slot_is_relevant(state):
        return
    state.resolved_slots["report_disposition"] = ResolvedSlot(
        name="report_disposition",
        value=value,
        source="structured_answer",
        evidence=["question_answer:report_disposition"],
        confidence="high",
    )


_MODEL_PROTECTED_SOURCES: frozenset[SlotSource] = frozenset(
    {"structured_answer", "flow_default", "attachment_structure"}
)
# Most flow defaults state a structural fact of the existing flow that the user
# has not contradicted. The purpose is different: read off the flow it describes
# what the flow does today, so an edit asking for something else must be able to
# replace it with cited, high-confidence evidence from the current turn.
_FLOW_OBSERVED_SLOT_NAMES: frozenset[str] = frozenset({"post_processing_goal"})


def carry_forward_persisted_planner_state(
    rebuilt: PlanningState,
    persisted: PlanningState | None,
    *,
    attached_file_ids: Collection[UUID],
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

    `attached_file_ids` is the current session membership. Requiring it keeps
    persisted file-derived evidence from outliving a detached attachment.
    """
    if persisted is None:
        return
    if rebuilt.mapped_file_limit.accepted_value is None:
        prior_limit = persisted.mapped_file_limit
        # A missing proposal means the current policy blocks new mapped
        # authoring (explicit opt-out or invalid policy); a previously accepted
        # limit must not survive that transition and re-enable publication.
        if (
            prior_limit.accepted_value is not None
            and rebuilt.mapped_file_limit.proposed_value is not None
            and prior_limit.accepted_value <= rebuilt.mapped_file_limit.proposed_value
        ):
            rebuilt.mapped_file_limit = MappedFileLimit(
                proposed_value=rebuilt.mapped_file_limit.proposed_value,
                accepted_value=prior_limit.accepted_value,
                provenance=prior_limit.provenance,
            )
    if (
        rebuilt.architecture_commit is None
        and persisted.architecture_commit is not None
    ):
        rebuilt.architecture_commit = persisted.architecture_commit
    current_file_ids = {item.file_id for item in rebuilt.file_roles}
    for file_role in persisted.file_roles:
        if file_role.file_id not in attached_file_ids:
            continue
        if file_role.file_id not in current_file_ids:
            rebuilt.file_roles.append(file_role)
            current_file_ids.add(file_role.file_id)
    _carry_forward_attachment_derived_slots(
        rebuilt,
        persisted,
        attached_file_ids=attached_file_ids,
    )
    carried_evidence = rebuilt.output_schema_evidence
    if carried_evidence is None and persisted.output_schema_evidence is not None:
        carried_evidence = _carryable_output_schema_evidence(
            persisted.output_schema_evidence,
            attached_file_ids=attached_file_ids,
        )
    carried_inference = rebuilt.example_output_schema_inference
    if carried_inference is None:
        carried_inference = _carryable_example_output_schema_inference(
            persisted.example_output_schema_inference,
            constraints=rebuilt.example_output_constraints,
            output_schema_evidence=carried_evidence,
            attached_file_ids=attached_file_ids,
        )
    if (
        carried_evidence is not None
        and carried_evidence.source == "inferred_example"
        and carried_inference is None
    ):
        carried_evidence = None
    if carried_evidence is not None or carried_inference is not None:
        rebuilt.replace_schema_resolution(
            input_evidence=rebuilt.input_schema_evidence,
            output_evidence=carried_evidence,
            example_inference=carried_inference,
        )
    # Carried-forward template roles can complete the explicit-template
    # picture only now, after persisted roles merged.
    resolve_docx_mode_from_template_evidence(rebuilt)


def _carry_forward_attachment_derived_slots(
    rebuilt: PlanningState,
    persisted: PlanningState,
    *,
    attached_file_ids: Collection[UUID],
) -> None:
    """Preserve slots resolved from file bytes across a conversation rebuild.

    Conversation-derived slots are the rebuild's job. Slots with source
    `attachment_structure` were resolved by inspecting attached bytes —
    template placeholders, structural markers — and no amount of
    conversation replay can reproduce them. Losing one made `commit_turn`
    re-derive a different architecture than the one it was committing, and
    the commit-invariance guard then refused every commit for the whole
    docx-template case family (2026-08-07, drift receipts on record).

    A slot is carried only while every file its evidence names is still
    attached, and never over a commit-grade slot the rebuild resolved
    itself — an explicit answer in conversation outranks structure.
    """

    attached = set(attached_file_ids)
    for name, slot in persisted.resolved_slots.items():
        if slot.source != "attachment_structure":
            continue
        current = rebuilt.resolved_slots.get(name)
        if current is not None and current.is_commit_grade:
            continue
        evidence_file_ids = _slot_evidence_file_ids(slot)
        if not evidence_file_ids or not evidence_file_ids <= attached:
            continue
        rebuilt.resolved_slots[name] = slot


def _slot_evidence_file_ids(slot: ResolvedSlot) -> set[UUID]:
    """File ids a structural slot's evidence names (`file:<uuid>:<marker>`).

    Unparseable entries yield no id, so a slot that cannot prove which
    files back it is never carried.
    """

    file_ids: set[UUID] = set()
    for entry in slot.evidence:
        if not entry.startswith("file:"):
            continue
        try:
            file_ids.add(UUID(entry.split(":", 2)[1]))
        except (IndexError, ValueError):
            return set()
    return file_ids


def _carryable_output_schema_evidence(
    evidence: SchemaEvidence,
    *,
    attached_file_ids: Collection[UUID],
) -> SchemaEvidence | None:
    if evidence.source == "declared_schema":
        return None

    attached = set(attached_file_ids)
    source_file_ids = set(evidence.source_file_ids)
    if evidence.source == "inferred_example":
        return evidence if source_file_ids and source_file_ids <= attached else None

    if evidence.truncated and source_file_ids and not source_file_ids <= attached:
        return None
    retained = [
        (marker, parsed)
        for marker in evidence.evidence
        if (parsed := _template_placeholder_marker(marker)) is not None
        and parsed[0] in attached
    ]
    if not retained:
        return None

    retained_placeholders = {placeholder for _, (_, placeholder) in retained}
    retained_source_markers = [
        marker
        for marker in evidence.evidence
        if _attachment_evidence_file_id(
            marker,
            TEMPLATE_PLACEHOLDER_SOURCE_EVIDENCE_SUFFIX,
        )
        in attached
    ]
    retained_source_file_ids = tuple(sorted(source_file_ids & attached, key=str))
    return build_schema_evidence(
        json_schema=_filter_template_placeholder_schema(
            evidence.json_schema,
            retained_placeholders=retained_placeholders,
        ),
        source=evidence.source,
        source_file_ids=retained_source_file_ids,
        confidence=evidence.confidence,
        evidence=(*retained_source_markers, *[marker for marker, _ in retained]),
        total_count=(
            evidence.total_count
            if evidence.truncated
            else len(retained_placeholders)
            if evidence.total_count is not None
            else None
        ),
        truncated=evidence.truncated,
    )


def _carryable_example_output_schema_inference(
    inference: ExampleOutputSchemaInferenceOutcome | None,
    *,
    constraints: ExampleOutputConstraintEvidence | None,
    output_schema_evidence: SchemaEvidence | None,
    attached_file_ids: Collection[UUID],
) -> ExampleOutputSchemaInferenceOutcome | None:
    if inference is None or constraints is None:
        return None
    source_file_ids = set(inference.source_file_ids)
    if not source_file_ids <= set(attached_file_ids):
        return None
    if not source_file_ids <= set(constraints.source_file_ids):
        return None
    if inference.status == "inferred":
        if (
            output_schema_evidence is None
            or output_schema_evidence.source != "inferred_example"
            or output_schema_evidence.source_file_ids != inference.source_file_ids
        ):
            return None
        return inference
    if inference.reason == "higher_priority_schema":
        return (
            inference
            if output_schema_evidence is not None
            and output_schema_evidence.source != "inferred_example"
            else None
        )
    return inference if output_schema_evidence is None else None


def _attachment_evidence_file_id(marker: str, suffix: str) -> UUID | None:
    if not marker.startswith("file:") or not marker.endswith(suffix):
        return None
    raw_file_id = marker.removeprefix("file:").removesuffix(suffix)
    try:
        return UUID(raw_file_id)
    except ValueError:
        return None


def _template_placeholder_marker(marker: str) -> tuple[UUID, str] | None:
    prefix = "file:"
    placeholder_separator = f":{TEMPLATE_PLACEHOLDER_EVIDENCE_PREFIX}"
    if not marker.startswith(prefix) or placeholder_separator not in marker:
        return None
    raw_file_id, placeholder = marker.removeprefix(prefix).split(
        placeholder_separator, 1
    )
    if not placeholder:
        return None
    try:
        file_id = UUID(raw_file_id)
    except ValueError:
        return None
    return file_id, placeholder


def _filter_template_placeholder_schema(
    schema: JsonObject,
    *,
    retained_placeholders: set[str],
) -> JsonObject:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return schema

    filtered = dict(schema)
    filtered_properties = {
        key: value for key, value in properties.items() if key in retained_placeholders
    }
    filtered["properties"] = filtered_properties

    required = schema.get("required")
    if isinstance(required, list):
        filtered["required"] = [
            item
            for item in required
            if isinstance(item, str) and item in filtered_properties
        ]

    return filtered


def merge_llm_resolved_slots(
    state: PlanningState,
    classification_result: SlotClassificationResult,
    *,
    prompt_hash: str,
    freeform_text: str,
    model_blocked_slots: frozenset[str] = frozenset(),
    settled_by_acceptance: frozenset[str] = frozenset(),
) -> None:
    """Overlay model slots without displacing explicit user or flow evidence.

    `settled_by_acceptance` names slots this classification may not touch
    because the user already accepted them and it cites nothing they have said
    since; `attested_slots_without_newer_evidence` resolves it.
    """
    if not prompt_hash.strip():
        raise ValueError("prompt_hash must be non-empty")

    apply_model_blocked_slots(state, model_blocked_slots=model_blocked_slots)
    _merge_model_checkpoint_updates(
        state,
        classification_result=classification_result,
    )
    _merge_model_result_obligations(
        state,
        classification_result=classification_result,
        prompt_hash=prompt_hash,
    )
    _merge_model_form_intake(
        state,
        classification_result=classification_result,
        prompt_hash=prompt_hash,
    )
    file_roles = _merged_model_file_roles(
        state.file_roles,
        classification_result=classification_result,
        prompt_hash=prompt_hash,
    )
    example_constraints = _merged_model_example_output_constraints(
        current=state.example_output_constraints,
        file_roles=file_roles,
        classification_result=classification_result,
    )
    if (
        file_roles != state.file_roles
        or example_constraints != state.example_output_constraints
    ):
        example_inference = state.example_output_schema_inference
        evidence = state.output_schema_evidence
        if not _example_output_inference_matches_constraints(
            example_inference,
            example_constraints,
        ):
            example_inference = None
            if evidence is not None and evidence.source == "inferred_example":
                evidence = None
        state.replace_attachment_interpretation(
            file_roles=file_roles,
            example_constraints=example_constraints,
            input_evidence=state.input_schema_evidence,
            output_evidence=evidence,
            example_inference=example_inference,
        )

    for classified_slot in classification_result.slots:
        if not _model_slot_is_persistable(classified_slot.slot_name):
            continue
        if classified_slot.slot_name in settled_by_acceptance:
            continue
        if classified_slot.slot_name in model_blocked_slots:
            _clear_nonprotected_model_slot(state, classified_slot.slot_name)
            continue
        if not classified_slot.evidence:
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
                *[item.planning_reference() for item in classified_slot.evidence],
            ],
            confidence=classified_slot.confidence,
            evidence_level=classified_slot.evidence_level,
        )

    _merge_model_named_result_evidence(
        state,
        classified_evidence=classification_result.named_result_evidence,
    )


def _merge_model_checkpoint_updates(
    state: PlanningState,
    *,
    classification_result: SlotClassificationResult,
) -> None:
    producer_kinds = [
        update.producer_kind for update in classification_result.checkpoint_updates
    ]
    if len(producer_kinds) != len(set(producer_kinds)):
        raise ValueError("checkpoint_updates must contain unique producer_kind values")
    intents_by_producer = {
        intent.producer_kind: intent for intent in state.checkpoint_intents
    }
    for update in classification_result.checkpoint_updates:
        if update.confidence == "low" or not update.evidence:
            raise ValueError("checkpoint update requires supported cited evidence")
        if update.operation == "clear":
            if update.mode is not None:
                raise ValueError("checkpoint clear must not carry a review mode")
            # A requested removal is a typed tombstone, not absence: absence
            # means "unchanged", which the edit lane must distinguish.
            intents_by_producer[update.producer_kind] = CheckpointIntent(
                producer_kind=update.producer_kind,
                operation="clear",
                mode=None,
                confidence=update.confidence,
                evidence=[item.planning_reference() for item in update.evidence],
            )
            continue
        if update.mode is None:
            raise ValueError("checkpoint update requires a review mode")
        intents_by_producer[update.producer_kind] = CheckpointIntent(
            producer_kind=update.producer_kind,
            operation="set",
            mode=update.mode,
            confidence=update.confidence,
            evidence=[item.planning_reference() for item in update.evidence],
        )
    state.checkpoint_intents = sorted(
        intents_by_producer.values(),
        key=lambda intent: intent.producer_kind,
    )


def _merge_model_named_result_evidence(
    state: PlanningState,
    *,
    classified_evidence: ClassifiedNamedResultDelta | None,
) -> None:
    if (
        classified_evidence is None
        or classified_evidence.confidence == "low"
        or not classified_evidence.evidence
    ):
        return
    if classified_evidence.operation == "clear":
        state.named_result_evidence = []
        return
    removed = {
        fold_result_field_name(name) for name in classified_evidence.removed_names
    }
    retained = [
        item
        for item in state.named_result_evidence
        if fold_result_field_name(item.name) not in removed
    ]
    cited_by_fold = {
        fold_result_field_name(item.name): item
        for item in classified_evidence.evidence_by_name
    }

    def _recited(
        name: str,
        *,
        prior_shape: NamedResultDeclaredShape | None,
    ) -> NamedResultEvidence:
        cited = cited_by_fold[fold_result_field_name(name)]
        return NamedResultEvidence(
            name=name,
            confidence=classified_evidence.confidence,
            # A re-citation without notation is silence, not a retraction:
            # writing `foo` again does not withdraw the `foo[]` the user
            # already declared. Only a different literal marker replaces the
            # shape, and only a removal clears the identity.
            declared_shape=cited.declared_shape or prior_shape,
            evidence=[
                evidence.planning_reference()
                for evidence in cited.evidence[:NAMED_RESULT_EVIDENCE_MAX_CITATIONS]
            ],
        )

    # Every valid re-citation replaces the identity it names: the newest
    # citation owns the spelling, the confidence, and the provenance, and it
    # keeps the position the identity already held.
    recited_by_fold = {
        fold_result_field_name(name): name for name in classified_evidence.names
    }
    named_results: list[NamedResultEvidence] = []
    replaced: set[str] = set()
    for item in retained:
        folded = fold_result_field_name(item.name)
        recited_name = recited_by_fold.get(folded)
        if recited_name is None:
            named_results.append(item)
            continue
        named_results.append(_recited(recited_name, prior_shape=item.declared_shape))
        replaced.add(folded)
    named_results.extend(
        _recited(name, prior_shape=None)
        for name in classified_evidence.names
        if fold_result_field_name(name) not in replaced
    )
    if len(named_results) > NAMED_RESULT_EVIDENCE_MAX_ITEMS:
        raise AIBuilderBadRequestException(
            "The named results exceed the Builder safety limit.",
            code=AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED,
            context={
                "reason": "named_result_count",
                "max_value": NAMED_RESULT_EVIDENCE_MAX_ITEMS,
                "actual_value": len(named_results),
            },
        )
    state.named_result_evidence = named_results


def _apply_replayed_named_result_evidence(
    state: PlanningState,
    *,
    snapshot: SlotClassificationNamedResultEvidenceMetadata | None,
) -> None:
    if snapshot is None or snapshot.confidence == "low" or not snapshot.evidence:
        return
    state.named_result_evidence = (
        list(snapshot.named_results) if snapshot.operation == "replace" else []
    )


def _merge_model_form_intake(
    state: PlanningState,
    *,
    classification_result: SlotClassificationResult,
    prompt_hash: str,
) -> None:
    form_intake = classification_result.form_intake
    if not _model_form_intake_is_persistable(form_intake):
        return
    assert form_intake is not None
    state.signals = [
        signal
        for signal in state.signals
        if not (
            signal.question_id == FORM_INTAKE_SIGNAL_ID and signal.source == "model"
        )
    ]
    existing = {
        signal.value
        for signal in state.signals
        if signal.question_id == FORM_INTAKE_SIGNAL_ID
    }
    for value in _form_intake_signal_values(form_intake):
        if value in existing:
            continue
        state.signals.append(
            PlanningSignal(
                question_id=FORM_INTAKE_SIGNAL_ID,
                value=value,
                confidence=form_intake.confidence,
                source="model",
                provenance=[
                    f"model:{FORM_INTAKE_SIGNAL_ID}:{prompt_hash}",
                    *[item.planning_reference() for item in form_intake.evidence],
                ],
            )
        )
        existing.add(value)


def _model_form_intake_is_persistable(
    form_intake: ClassifiedFormIntake | None,
) -> bool:
    if form_intake is None:
        return False
    return form_intake.confidence != "low" and bool(form_intake.evidence)


def _form_intake_signal_values(
    form_intake: ClassifiedFormIntake,
) -> tuple[str, ...]:
    values: list[str] = []
    if form_intake.needs_form_fields or form_intake.sectioned_form_intake:
        values.append(FORM_INTAKE_NEEDS_FIELDS_SIGNAL)
    if form_intake.sectioned_form_intake:
        values.append(SECTIONED_FORM_INTAKE_SIGNAL)
    return tuple(values)


def _merged_model_file_roles(
    current: list[FileRoleEvidence],
    *,
    classification_result: SlotClassificationResult,
    prompt_hash: str,
) -> list[FileRoleEvidence]:
    if not classification_result.file_roles or not current:
        return current
    roles_by_id = {item.file_id: item for item in current}
    changed = False
    for classified_role in classification_result.file_roles:
        existing_role = roles_by_id.get(classified_role.file_id)
        if existing_role is None:
            continue
        if not _model_file_role_can_replace(
            existing_role=existing_role,
            classified_role=classified_role,
        ):
            continue
        # Every turn re-classifies. An unchanged decision must not touch the
        # persisted role: appending a fresh model:file_role:<hash> plus a
        # duplicate quote on each identical decision grew the evidence
        # without bound and moved every state hash derived from it — the
        # requirements-confirmation loop was this churn.
        if (
            existing_role.source == "model"
            and existing_role.role == classified_role.role
            and existing_role.confidence == classified_role.confidence
            and existing_role.evidence_level == classified_role.evidence_level
        ):
            continue
        # A new decision carries its own evidence; stacking it onto the old
        # decision's evidence would describe two decisions at once.
        roles_by_id[classified_role.file_id] = existing_role.model_copy(
            update={
                "role": classified_role.role,
                "source": "model",
                "confidence": classified_role.confidence,
                "evidence_level": classified_role.evidence_level,
                "evidence": [
                    f"model:file_role:{prompt_hash}",
                    *[item.planning_reference() for item in classified_role.evidence],
                ],
                "candidate_roles": _merged_file_role_candidates(
                    existing_role.candidate_roles or [existing_role.role],
                    classified_role.role,
                ),
            }
        )
        changed = True
    if not changed:
        return current
    return [roles_by_id[item.file_id] for item in current]


def _merged_model_example_output_constraints(
    *,
    current: ExampleOutputConstraintEvidence | None,
    file_roles: list[FileRoleEvidence],
    classification_result: SlotClassificationResult,
) -> ExampleOutputConstraintEvidence | None:
    constraints = classification_result.example_output_constraints
    if constraints is None:
        return (
            current
            if _example_output_constraints_match_file_roles(current, file_roles)
            else None
        )
    if (
        constraints.confidence == "low"
        or not _example_output_constraints_match_file_roles(
            constraints,
            file_roles,
        )
    ):
        return None
    if _describes_same_example_evidence(current, constraints):
        # The same files, seen the same way, re-read by the model. Its wording
        # moves anyway — headings vanish and reappear, style descriptions
        # switch language — and every move rewrote the requirements summary,
        # so the confirmation the user had just given could never match again.
        # New evidence replaces an interpretation; re-reading the old evidence
        # does not.
        return current
    return constraints


def _describes_same_example_evidence(
    current: ExampleOutputConstraintEvidence | None,
    candidate: ExampleOutputConstraintEvidence,
) -> bool:
    """Whether the classifier is re-reading exactly the evidence already read.

    Citations are part of the answer: a user who writes a new instruction about
    the example produces a new citation, and that is new user evidence which
    must replace the interpretation. Only identical files, identical coverage
    and identical citations mean nothing was added.
    """

    if current is None:
        return False
    return (
        current.source_file_ids == candidate.source_file_ids
        and current.source_coverage == candidate.source_coverage
        and current.citations == candidate.citations
    )


def _example_output_inference_matches_constraints(
    inference: ExampleOutputSchemaInferenceOutcome | None,
    constraints: ExampleOutputConstraintEvidence | None,
) -> bool:
    if inference is None:
        return True
    return constraints is not None and set(inference.source_file_ids) <= set(
        constraints.source_file_ids
    )


def _example_output_constraints_match_file_roles(
    constraints: ExampleOutputConstraintEvidence | None,
    file_roles: list[FileRoleEvidence],
) -> bool:
    if constraints is None:
        return True
    roles_by_file_id = {item.file_id: item for item in file_roles}
    coverage_by_file_id = {
        item.file_id: item.coverage for item in constraints.source_coverage
    }
    return all(
        (role := roles_by_file_id.get(file_id)) is not None
        and role.role == "example_output"
        and role.coverage == coverage_by_file_id[file_id]
        for file_id in constraints.source_file_ids
    )


def _model_file_role_can_replace(
    *,
    existing_role: FileRoleEvidence,
    classified_role: ClassifiedFileRole,
) -> bool:
    if classified_role.confidence == "low":
        return False
    if not classified_role.evidence:
        return False
    if existing_role.source == "structured_answer":
        return False
    if existing_role.source == "heuristic" and existing_role.role != "context_only":
        return False
    if existing_role.source == "heuristic" and existing_role.confidence == "high":
        return False
    if existing_role.source != "model":
        return True
    if (
        existing_role.evidence_level == "explicit"
        and classified_role.evidence_level != "explicit"
    ):
        return False
    if existing_role.role == classified_role.role:
        return True
    # A different quote from the same message is a reinterpretation, not new
    # evidence. A role change needs a source the prior decision did not cite.
    return any(
        not any(
            planning_reference_cites_source(reference, source_id=evidence.source_id)
            for reference in existing_role.evidence
        )
        for evidence in classified_role.evidence
    )


def _merged_file_role_candidates(
    existing_candidates: list[FileRole],
    classified_role: FileRole,
) -> list[FileRole]:
    merged: list[FileRole] = []
    for candidate in (*existing_candidates, classified_role):
        if candidate not in merged:
            merged.append(candidate)
    return merged


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
    _reconcile_dependent_slot_relevance(state)


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
    return _dependent_slot_is_relevant(
        slot_name=slot_name,
        state=state,
        unresolved_values_are_relevant=True,
        require_commit_grade_primary_input=True,
    )


_TEMPLATE_DERIVED_DOCX_MODE_SOURCES: frozenset[SlotSource] = frozenset(
    {"model", "attachment_structure"}
)


def resolve_docx_mode_from_template_evidence(state: PlanningState) -> None:
    """Reconcile docx fill mode with the template evidence available now.

    Two kinds of evidence say a docx is produced by filling a template: the
    user's own words, classified onto the file, and the placeholders in the
    file's own bytes. They reach the same conclusion, so this is one decision
    with one owner rather than a rule per evidence kind — only the recorded
    provenance differs, and placeholders take it because a document that
    carries fields is its own proof.

    Exactly one template settles the mode. Several do not: which one the flow
    fills is the user's choice, so the question stays, as it does for a merely
    inferred role or no template at all. Any authoritative source outranks this
    rule; only a policy default and this rule's own earlier conclusion are
    replaceable, and a `model` or `attachment_structure` mode for this slot is
    always the latter, because the slot is not model-resolvable
    (`NON_LLM_RESOLVABLE_SLOT_NAMES`).

    The conclusion is derived, never remembered — but only a contradiction
    revokes it, not silence. A role that is no longer a template, a second
    template, or a terminal that is no longer docx all revoke it. Roles missing
    altogether do not: a state rebuilt without its attachments has none, and a
    mode read out of file bytes cannot be recovered from conversation
    (`_carry_forward_attachment_derived_slots` owns why).
    """

    current = state.resolved_slots.get("docx_output_mode")
    resolved_here = (
        current is not None and current.source in _TEMPLATE_DERIVED_DOCX_MODE_SOURCES
    )
    if current is not None and not resolved_here and current.source != "policy_default":
        return
    terminal_output = state.resolved_slots.get("terminal_output")
    terminal_still_docx = (
        terminal_output is None or terminal_output.value == "docx_document"
    )
    if resolved_here and not state.file_roles and terminal_still_docx:
        return
    template = _sole_template_role_settling_fill_mode(state)
    if (
        template is None
        or terminal_output is None
        or terminal_output.value != "docx_document"
    ):
        if resolved_here:
            del state.resolved_slots["docx_output_mode"]
        return
    state.resolved_slots["docx_output_mode"] = _template_fill_docx_mode(template)


def _sole_template_role_settling_fill_mode(
    state: PlanningState,
) -> FileRoleEvidence | None:
    templates = [item for item in state.file_roles if item.role == "template"]
    if len(templates) != 1:
        return None
    template = templates[0]
    if template.template_placeholders or _is_explicit_model_template(template):
        return template
    return None


def _is_explicit_model_template(template: FileRoleEvidence) -> bool:
    return (
        template.source == "model"
        and template.evidence_level == "explicit"
        and template.confidence in {"high", "medium"}
        and any(entry.startswith("quote:") for entry in template.evidence)
    )


def _template_fill_docx_mode(template: FileRoleEvidence) -> ResolvedSlot:
    if template.template_placeholders:
        return ResolvedSlot(
            name="docx_output_mode",
            value="template_fill_docx",
            source="attachment_structure",
            confidence="high",
            evidence=[
                f"file:{template.file_id}:{TEMPLATE_PLACEHOLDER_EVIDENCE_PREFIX}"
                f"{placeholder}"
                for placeholder in template.template_placeholders
            ][:3],
        )
    return ResolvedSlot(
        name="docx_output_mode",
        value="template_fill_docx",
        source="model",
        confidence=template.confidence,
        evidence=[entry for entry in template.evidence if entry.startswith("quote:")],
        evidence_level="explicit",
    )


def _reconcile_dependent_slot_relevance(state: PlanningState) -> None:
    for slot_name in tuple(state.resolved_slots):
        if not _dependent_slot_is_relevant(
            slot_name=slot_name,
            state=state,
            unresolved_values_are_relevant=True,
            require_commit_grade_primary_input=False,
        ):
            state.resolved_slots.pop(slot_name, None)


def _dependent_slot_is_relevant(
    *,
    slot_name: str,
    state: PlanningState,
    unresolved_values_are_relevant: bool,
    require_commit_grade_primary_input: bool,
) -> bool:
    primary_runtime_input = state.resolved_slots.get("primary_runtime_input")
    terminal_output = state.resolved_slots.get("terminal_output")
    primary_value = None
    if primary_runtime_input is not None and (
        not require_commit_grade_primary_input or primary_runtime_input.is_commit_grade
    ):
        primary_value = primary_runtime_input.value
    terminal_value = terminal_output.value if terminal_output is not None else None

    if slot_name in {"comparison_scope", "document_material_scope"}:
        return comparison_scope_is_relevant(
            primary_runtime_input=primary_value,
            unresolved_values_are_relevant=unresolved_values_are_relevant,
        )
    if slot_name == "report_disposition":
        return _report_disposition_slot_is_relevant(
            state,
            unresolved_values_are_relevant=unresolved_values_are_relevant,
        )
    if slot_name == "docx_output_mode":
        return terminal_value is None or terminal_value == "docx_document"
    if slot_name == "pdf_generation_mode":
        return terminal_value is None or terminal_value == "pdf_document"
    if slot_name != "structured_io_contract":
        return True
    input_incompatible = primary_value is not None and primary_value != "json"
    output_incompatible = (
        terminal_value is not None and terminal_value != "structured_json"
    )
    return not input_incompatible and not output_incompatible


def _report_disposition_slot_is_relevant(
    state: PlanningState,
    *,
    unresolved_values_are_relevant: bool = True,
) -> bool:
    primary_runtime_input = state.resolved_slots.get("primary_runtime_input")
    terminal_output = state.resolved_slots.get("terminal_output")
    document_material_scope = state.resolved_slots.get("document_material_scope")
    docx_output_mode = state.resolved_slots.get("docx_output_mode")
    return report_disposition_is_relevant(
        primary_runtime_input=(
            primary_runtime_input.value if primary_runtime_input is not None else None
        ),
        terminal_output=(
            terminal_output.value if terminal_output is not None else None
        ),
        document_material_scope=(
            document_material_scope.value
            if document_material_scope is not None
            else None
        ),
        docx_output_mode=(
            docx_output_mode.value if docx_output_mode is not None else None
        ),
        unresolved_values_are_relevant=unresolved_values_are_relevant,
    )


def _model_slot_can_replace(
    *,
    existing_slot: ResolvedSlot | None,
    model_confidence: SlotConfidence,
) -> bool:
    """Protect authoritative sources while permitting cited model corrections."""
    if existing_slot is None:
        return model_confidence in {"high", "medium"}
    if (
        existing_slot.source == "flow_default"
        and existing_slot.name in _FLOW_OBSERVED_SLOT_NAMES
    ):
        return model_confidence == "high"
    if existing_slot.source in _MODEL_PROTECTED_SOURCES:
        return False
    if existing_slot.source == "requirements_summary":
        return model_confidence == "high"
    if existing_slot.source == "policy_default":
        return model_confidence == "high"
    if existing_slot.source == "heuristic":
        return model_confidence in {"high", "medium"}
    if existing_slot.source == "model":
        return model_confidence in {"high", "medium"}
    return False


def _resolve_slots(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None,
) -> dict[str, ResolvedSlot]:
    answer_signals = extract_answer_signals(conversation)
    requirements_state = resolve_requirements_state(conversation)
    # What the user accepted, not what is currently on screen: a disclosure the
    # user has not answered yet must not unpin the facts an earlier one settled.
    requirements_summary_values = attested_requirement_values(
        requirements_state.attested_summary
    )
    freeform_text = _semantic_planning_text(
        aggregate_unprompted_user_text(conversation),
        requirements_state,
    )
    flow_defaults = build_flow_discovery_defaults(flow)
    input_intent = resolve_input_intent(freeform_text, answer_signals, flow=flow)
    output_intent = resolve_output_intent(
        freeform_text,
        answer_signals,
        flow_defaults=flow_defaults,
        conversation=conversation,
    )

    slots: dict[str, ResolvedSlot] = {}

    primary_runtime_input = (
        _single_slot_value(
            answer_signals=answer_signals,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            question_id="primary_runtime_input",
        )
        or input_intent.primary_runtime_input
    )
    if primary_runtime_input != "unknown":
        slots["primary_runtime_input"] = _build_slot(
            name="primary_runtime_input",
            value=primary_runtime_input,
            question_id="primary_runtime_input",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=primary_runtime_input,
        )

    terminal_output = (
        _single_slot_value(
            answer_signals=answer_signals,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            question_id="terminal_output",
        )
        or output_intent.terminal_output
    )
    if terminal_output is not None:
        slots["terminal_output"] = _build_slot(
            name="terminal_output",
            value=terminal_output,
            question_id="terminal_output",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=terminal_output,
        )

    docx_output_mode = (
        _single_slot_value(
            answer_signals=answer_signals,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            question_id="docx_output_mode",
        )
        or output_intent.docx_output_mode
    )
    if docx_output_mode is not None:
        slots["docx_output_mode"] = _build_slot(
            name="docx_output_mode",
            value=docx_output_mode,
            question_id="docx_output_mode",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=docx_output_mode,
        )

    pdf_generation_mode = (
        _single_slot_value(
            answer_signals=answer_signals,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            question_id="pdf_generation_mode",
        )
        or output_intent.pdf_generation_mode
    )
    if pdf_generation_mode is not None:
        slots["pdf_generation_mode"] = _build_slot(
            name="pdf_generation_mode",
            value=pdf_generation_mode,
            question_id="pdf_generation_mode",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=pdf_generation_mode,
        )

    document_material_scope = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        requirements_summary_values=requirements_summary_values,
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
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=document_material_scope,
        )

    report_disposition = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        requirements_summary_values=requirements_summary_values,
        question_id="report_disposition",
    )
    if report_disposition is not None and report_disposition_is_relevant(
        primary_runtime_input=primary_runtime_input,
        terminal_output=terminal_output,
        document_material_scope=document_material_scope,
        docx_output_mode=docx_output_mode,
        unresolved_values_are_relevant=False,
    ):
        slots["report_disposition"] = _build_slot(
            name="report_disposition",
            value=report_disposition,
            question_id="report_disposition",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=report_disposition,
        )

    # No policy default: ambiguous comparison prompts must ask for architecture.
    comparison_scope = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        requirements_summary_values=requirements_summary_values,
        question_id="comparison_scope",
    )
    if comparison_scope is not None:
        slots["comparison_scope"] = _build_slot(
            name="comparison_scope",
            value=comparison_scope,
            question_id="comparison_scope",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=comparison_scope,
        )

    post_processing_goal = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        requirements_summary_values=requirements_summary_values,
        question_id="post_processing_goal",
    )
    if post_processing_goal is not None:
        slots["post_processing_goal"] = _build_slot(
            name="post_processing_goal",
            value=post_processing_goal,
            question_id="post_processing_goal",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=post_processing_goal,
        )

    structured_io_contract = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        requirements_summary_values=requirements_summary_values,
        question_id="structured_io_contract",
    )
    if structured_io_contract is not None:
        slots["structured_io_contract"] = _build_slot(
            name="structured_io_contract",
            value=structured_io_contract,
            question_id="structured_io_contract",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
            slot_value=structured_io_contract,
        )

    runtime_metadata_fields = _single_slot_value(
        answer_signals=answer_signals,
        flow_defaults=flow_defaults,
        requirements_summary_values=requirements_summary_values,
        question_id="runtime_metadata_fields",
    )
    if runtime_metadata_fields is not None:
        slots["runtime_metadata_fields"] = _build_slot(
            name="runtime_metadata_fields",
            value=runtime_metadata_fields,
            question_id="runtime_metadata_fields",
            conversation=conversation,
            flow_defaults=flow_defaults,
            requirements_summary_values=requirements_summary_values,
            freeform_text=freeform_text,
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
    requirements_summary_values: dict[str, str],
    freeform_text: str,
    slot_value: str,
) -> ResolvedSlot:
    source, evidence, confidence = _resolve_slot_origin(
        question_id=question_id,
        conversation=conversation,
        flow_defaults=flow_defaults,
        requirements_summary_values=requirements_summary_values,
        freeform_text=freeform_text,
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
    requirements_summary_values: dict[str, str],
    freeform_text: str,
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

    if requirements_summary_values.get(question_id) == slot_value:
        return (
            "requirements_summary",
            (_attested_requirement_evidence(question_id, slot_value),),
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


def attested_requirement_values(
    summary: RequirementsSummaryPayload | None,
) -> dict[str, str]:
    """The typed facts a user accepted by confirming this disclosure.

    Accepting a disclosure makes its values the user's own answer, which is
    what lets an inferred value drive an irreversible decision. Only values
    the vocabulary still admits are returned, so a disclosure persisted under
    an older vocabulary cannot resurrect a value the planner no longer has.
    """

    if summary is None:
        return {}
    return {
        requirement.requirement_id: requirement.selected_value
        for requirement in summary.resolved_requirements
        if requirement.requirement_id in KNOWN_REQUIREMENT_SLOT_NAMES
        and requirement.selected_value in legal_slot_values(requirement.requirement_id)
    }


def attested_slots_without_newer_evidence(
    classification_result: SlotClassificationResult,
    *,
    conversation: list[ConversationMessage],
    cited_message_ids_by_source: Mapping[str, str | None],
    classified_at_index: int,
) -> frozenset[str]:
    """Accepted slots this later classification cites nothing newer than for.

    Accepting a disclosure makes its values the user's own answer, which is what
    lets them drive the architecture. A later reading of the very sentences the
    user already answered is therefore not the user changing their mind, however
    confident it is: an open prompt that names two plausible results can be read
    either way, and the reading the user accepted is the one that settled it.

    Only a classification made *before* the acceptance is part of what was
    accepted, and those are how the accepted state is reconstructed at all, so
    they are replayed untouched. A confirmation that falls through to an
    ordinary classified turn persists that turn's reading on the confirmation
    message itself: it shares the confirmation's position but the disclosure
    the user answered was built before it, so it is a re-reading like any other.

    Freshness is chronology, not the current turn: the user says something new
    once, and a turn whose classification failed must still be able to act on it
    later. A citation is newer when the message it quotes comes after the
    confirmation. A quoted message that compaction has since dropped cannot be
    placed, so it counts as already-answered and the accepted value stands.
    """

    attested = resolve_attested_disclosure(conversation)
    if attested is None or classified_at_index < attested.confirmation_index:
        return frozenset()
    accepted = attested_requirement_values(attested.summary)
    if not accepted:
        return frozenset()
    message_order = {
        message.message_id: index for index, message in enumerate(conversation)
    }
    return frozenset(
        slot.slot_name
        for slot in classification_result.slots
        if slot.slot_name in accepted
        and not _cites_evidence_after(
            slot,
            attested=attested,
            cited_message_ids_by_source=cited_message_ids_by_source,
            message_order=message_order,
        )
    )


def _cites_evidence_after(
    slot: ClassifiedSlot,
    *,
    attested: AttestedDisclosure,
    cited_message_ids_by_source: Mapping[str, str | None],
    message_order: Mapping[str, int],
) -> bool:
    for item in slot.evidence:
        message_id = cited_message_ids_by_source.get(item.source_id)
        if message_id is None:
            continue
        position = message_order.get(message_id)
        if position is not None and position > attested.confirmation_index:
            return True
    return False


def apply_attested_requirements(
    state: PlanningState,
    summary: RequirementsSummaryPayload | None,
) -> None:
    """Regrade slots the user accepted, on a state built before they did.

    A disclosure is persisted before the user answers it, so the state that
    produced it still grades its own inferences as model evidence. The
    acknowledgment resolves entirely from that persisted state, and only
    commit-grade facts reach the architecture — so without this the plan is
    built without the very requirements the user just accepted.

    Values are never changed here, only their provenance, exactly as the
    deterministic rebuild attributes them.
    """

    for requirement_id, value in attested_requirement_values(summary).items():
        slot = state.resolved_slots.get(requirement_id)
        if slot is None or slot.value != value:
            continue
        if not _attestation_outranks(slot):
            continue
        state.resolved_slots[requirement_id] = _requirements_summary_slot(
            requirement_id,
            value,
        )


def _attestation_outranks(slot: ResolvedSlot) -> bool:
    """Whether acceptance regrades this slot, by the rebuild's own precedence.

    The deterministic rebuild already ranks an attested value against every
    other source. Restating that ranking here would let the two disagree, and
    a fast path that grades a slot differently from the rebuild discloses a
    different record than the one it just persisted.
    """

    if slot.source in _MODEL_PROTECTED_SOURCES:
        return False
    if slot.source == "model":
        return not _model_slot_can_replace(
            existing_slot=_requirements_summary_slot(slot.name, slot.value),
            model_confidence=slot.confidence,
        )
    return True


def _attested_requirement_evidence(name: str, value: str) -> str:
    return f"requirements_summary.resolved_requirements:{name}={value}"


def _requirements_summary_slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="requirements_summary",
        evidence=[_attested_requirement_evidence(name, value)],
        confidence="high",
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
    if question_id in {
        "document_material_scope",
        "comparison_scope",
        "report_disposition",
    }:
        return _heuristic_text_signal_confidence(
            question_id=question_id,
            slot_value=slot_value,
            freeform_text=freeform_text,
        )
    if question_id == "runtime_metadata_fields":
        inferred_runtime_metadata = infer_runtime_metadata_slot(freeform_text)
        if (
            slot_value == NO_EXTRA_RUNTIME_METADATA
            and inferred_runtime_metadata == NO_EXTRA_RUNTIME_METADATA
        ):
            return "high"
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
    requirements_summary_values: dict[str, str],
    question_id: str,
) -> str | None:
    for values in (
        answer_signals.get(question_id),
        flow_defaults.get(question_id),
    ):
        if values is None:
            continue
        if len(values) != 1:
            return None
        return next(iter(values))
    return requirements_summary_values.get(question_id)
