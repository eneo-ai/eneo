"""Ordered edit compiler for the AI Builder.

Compiles the model-visible ordered edit proposal into the canonical authoring
spec plus the edit approval metadata the user approves. The key principle is
that every existing step is either represented in order or explicitly removed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_authoring_projection import (
    MaterializedAddStep,
    MaterializedOrderedEditProposal,
    MaterializedOrderedEditStep,
    compile_ordered_edit_proposal,
    materialize_ordered_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_domain_models import FlowBuilderEditApproval
from eneo.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    EditConfidence,
    FlowEditDiff,
    FormFieldChange,
    MetadataChange,
    StepChange,
    StepChangeField,
    StepFieldChange,
)
from eneo.flows.ai_builder.ai_builder_flow_schema_values import FlowInputFieldProvenance
from eneo.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
)
from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
    split_primary_runtime_input_shadow_names,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ModifyExistingStep,
    OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    StepNormalizationChange,
    normalize_ai_builder_spec,
)
from eneo.flows.ai_builder.ai_builder_template_attachment_contract import (
    MAX_TEMPLATE_PREPARATION_STAGES,
    apply_template_attachment_contract,
    template_preparation_stage_limit_exceeded,
)
from eneo.flows.application.flow_authoring_description_semantics import (
    FlowSemanticSignature,
)
from eneo.flows.application.flow_authoring_snapshot import current_flow_authoring_spec
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputType,
    StepSpec,
)
from eneo.flows.input_binding_contract_rules import (
    SOURCE_REFS_BINDING_KEY,
    question_binding,
    source_ref_bindings,
)
from eneo.flows.step_lineage import (
    existing_step_order_from_ref,
    existing_step_ref_for_order,
)

_RUNTIME_STEP_ALIAS_PATTERN = re.compile(r"\{\{\s*step_(\d+)(\.[^{}]+?)\s*\}\}")
_RUNTIME_STEP_REF_PATTERN = re.compile(r"^step_(\d+)$")


@dataclass(frozen=True, slots=True)
class _PreparedOrderedEditProposal:
    proposal: MaterializedOrderedEditProposal
    warnings: list[str]
    shadowed_primary_input_fields: list[str]
    form_field_provenance: dict[str, FlowInputFieldProvenance]


@dataclass(frozen=True, slots=True)
class EditCompilationResult:
    spec: FlowDraftSpecCore
    # The approval of what the model authored, read before session
    # preparation: it bounds the authored effect. The user approves the one
    # from approval_for_prepared_spec, never this one.
    authored_approval: FlowBuilderEditApproval
    # The published flow both approvals' diffs read against.
    base_spec: FlowDraftSpecCore

    def approval_for_prepared_spec(
        self, prepared_spec: FlowDraftSpecCore
    ) -> FlowBuilderEditApproval:
        """The approval whose diff describes ``prepared_spec``.

        Session preparation rewrites the compiled spec after this compiler
        has run (duplicate step names, resource canonicalisation, terminal
        output alignment), so the diff the user approves is read again from
        the same baseline against the spec that is actually returned.
        """

        step_changes = _build_step_changes(
            base_spec=self.base_spec,
            compiled_steps=prepared_spec.steps,
            removed_refs=self.authored_approval.removed_existing_step_refs,
        )
        diff = self.authored_approval.diff.model_copy(
            update={
                "step_changes": step_changes,
                "net_steps_added": sum(1 for c in step_changes if c.kind == "added"),
                "net_steps_removed": sum(
                    1 for c in step_changes if c.kind == "removed"
                ),
            }
        )
        return self.authored_approval.model_copy(
            update={
                "diff": diff,
                "confidence": _compute_confidence(
                    step_changes=step_changes,
                    form_changes=diff.form_changes,
                    warnings=self.authored_approval.warnings,
                ),
            }
        )


def compile_edit_proposal(
    proposal: OrderedEditProposal,
    current_steps: list[FlowStep],
    base_flow_revision: int,
    *,
    flow_name: str | None = None,
    flow_description: str | None = None,
    current_metadata_json: dict[str, Any] | None = None,
    assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
    requested_primary_runtime_input_type: InputType | None = None,
    ui_language: str | None = None,
    mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
    selected_template_count: int | None = None,
    selected_template_placeholders: tuple[str, ...] | None = None,
) -> EditCompilationResult:
    """Compile an ordered edit proposal into a concrete flow preview + diff."""
    primary_runtime_input_type = (
        requested_primary_runtime_input_type
        or _primary_runtime_input_type_from_steps(current_steps)
    )
    materialized_proposal = materialize_ordered_edit_proposal(
        proposal,
        primary_runtime_input_type=primary_runtime_input_type,
        primary_runtime_required=(
            _primary_runtime_required_from_steps(current_steps)
            if requested_primary_runtime_input_type is not None
            else False
        ),
    )
    prepared = _prepare_ordered_edit_proposal(
        proposal=materialized_proposal,
        current_steps=current_steps,
        current_metadata_json=current_metadata_json,
        primary_runtime_input_type=primary_runtime_input_type,
    )
    base_form_fields = extract_form_fields_from_metadata(current_metadata_json)
    base_spec = current_flow_authoring_spec(
        current_steps=current_steps,
        flow_name=flow_name,
        flow_description=flow_description,
        assistant_snapshots=assistant_snapshots,
        assistant_snapshot_projector=(
            resource_catalog.assistant_spec_from_snapshot
            if resource_catalog is not None
            else None
        ),
        form_fields=base_form_fields,
    )
    compiled_spec = compile_ordered_edit_proposal(
        base_spec=base_spec,
        proposal=prepared.proposal,
        ui_language=ui_language,
    )
    compiled_steps = compiled_spec.steps

    compiled_steps = _canonicalize_existing_runtime_aliases(compiled_steps)
    normalized_spec, normalization_changes = normalize_ai_builder_spec(
        FlowDraftSpecCore(
            flow_name=normalize_flow_name(compiled_spec.flow_name),
            flow_description=compiled_spec.flow_description,
            steps=compiled_steps,
            form_fields=compiled_spec.form_fields,
            document_body_writer_step_refs=(
                compiled_spec.document_body_writer_step_refs
            ),
        ),
        ui_language=ui_language,
    )
    if selected_template_count is not None:
        normalized_spec = apply_template_attachment_contract(
            normalized_spec,
            selected_template_count=selected_template_count,
            placeholders=selected_template_placeholders,
        )
    compiled_steps = normalized_spec.steps
    final_name = normalized_spec.flow_name
    final_description = normalized_spec.flow_description
    compiled_form_fields = normalized_spec.form_fields
    form_changes = _build_form_field_changes(base_form_fields, compiled_form_fields)

    compiled_spec = FlowDraftSpecCore(
        flow_name=final_name,
        flow_description=final_description,
        steps=compiled_steps,
        form_fields=compiled_form_fields,
        document_body_writer_step_refs=(normalized_spec.document_body_writer_step_refs),
    )
    if template_preparation_stage_limit_exceeded(compiled_spec):
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            repair_disposition="model_correctable",
            detail=(
                "DOCX template-fill flows support at most "
                f"{MAX_TEMPLATE_PREPARATION_STAGES} semantic preparation stages. "
                "Consolidate related analysis, validation, or writing stages and "
                "try again."
            ),
            log_context={
                "failure_code": "template_preparation_stage_limit_exceeded",
                "reason": "template_preparation_stage_limit_exceeded",
            },
        )

    advisories: list[EditAdvisory] = _build_normalization_advisories(
        normalization_changes
    )
    advisories.extend(
        _build_description_advisories(
            proposal=prepared.proposal,
            base_spec=base_spec,
            compiled_steps=compiled_steps,
            current_description=flow_description,
        )
    )
    advisories.extend(
        _build_primary_input_shadow_advisories(
            field_names=prepared.shadowed_primary_input_fields,
            primary_runtime_input_type=primary_runtime_input_type,
            field_provenance=prepared.form_field_provenance,
        )
    )
    advisories.extend(
        _mapped_file_limit_policy_advisories(
            current_steps=current_steps,
            mapped_execution_policy=mapped_execution_policy,
        )
    )

    step_changes = _build_step_changes(
        base_spec=base_spec,
        compiled_steps=compiled_steps,
        removed_refs=prepared.proposal.removed_existing_step_refs,
    )

    metadata_changes: list[MetadataChange] = []
    flow_property_changes: dict[str, tuple[Any, Any]] = {}
    if "flow_name" in prepared.proposal.model_fields_set and final_name != flow_name:
        flow_property_changes["flow_name"] = (flow_name, final_name)
    previous_description = flow_description or ""
    if final_description != previous_description:
        flow_property_changes["flow_description"] = (
            flow_description,
            final_description,
        )

    net_added = sum(1 for c in step_changes if c.kind == "added")
    net_removed = sum(1 for c in step_changes if c.kind == "removed")

    diff = FlowEditDiff(
        step_changes=step_changes,
        form_changes=form_changes,
        metadata_changes=metadata_changes,
        flow_property_changes=flow_property_changes,
        net_steps_added=net_added,
        net_steps_removed=net_removed,
    )

    risk_flags: list[str] = []
    if prepared.proposal.removed_existing_step_refs:
        risk_flags.append("step_removal")
    confidence = _compute_confidence(
        step_changes=step_changes,
        form_changes=form_changes,
        warnings=prepared.warnings,
    )

    return EditCompilationResult(
        spec=compiled_spec,
        authored_approval=FlowBuilderEditApproval(
            base_flow_revision=base_flow_revision,
            removed_existing_step_refs=prepared.proposal.removed_existing_step_refs,
            diff=diff,
            warnings=prepared.warnings,
            advisories=advisories,
            risk_flags=risk_flags,
            confidence=confidence,
        ),
        base_spec=base_spec,
    )


def _prepare_ordered_edit_proposal(
    *,
    proposal: MaterializedOrderedEditProposal,
    current_steps: list[FlowStep],
    current_metadata_json: dict[str, Any] | None,
    primary_runtime_input_type: InputType | None,
) -> _PreparedOrderedEditProposal:
    warnings: list[str] = []
    prepared, dropped_step_field_names = _sanitize_shadowed_primary_inputs(
        proposal=proposal,
        primary_runtime_input_type=primary_runtime_input_type,
    )
    prepared, dropped_declared_field_names = _sanitize_shadowed_form_fields(
        proposal=prepared,
        base_form_fields=extract_form_fields_from_metadata(current_metadata_json),
        primary_runtime_input_type=primary_runtime_input_type,
    )
    prepared = _repair_leading_audio_shape(
        proposal=prepared,
        current_steps=current_steps,
        warnings=warnings,
    )
    return _PreparedOrderedEditProposal(
        proposal=prepared,
        warnings=warnings,
        shadowed_primary_input_fields=[
            *dropped_step_field_names,
            *dropped_declared_field_names,
        ],
        form_field_provenance=prepared.form_field_provenance,
    )


def _sanitize_shadowed_primary_inputs(
    *,
    proposal: MaterializedOrderedEditProposal,
    primary_runtime_input_type: InputType | None,
) -> tuple[MaterializedOrderedEditProposal, list[str]]:
    steps: list[MaterializedOrderedEditStep] = []
    dropped_field_names: list[str] = []
    changed = False

    for item in proposal.steps:
        if isinstance(item, MaterializedAddStep):
            step, dropped = _without_primary_runtime_shadow_fields(
                item.step,
                primary_runtime_input_type=primary_runtime_input_type,
            )
            dropped_field_names.extend(dropped)
            if step is item.step:
                steps.append(item)
            else:
                steps.append(item.model_copy(update={"step": step}))
                changed = True
            continue

        if "uses_form_fields" not in item.model_fields_set:
            steps.append(item)
            continue
        filtered, dropped = split_primary_runtime_input_shadow_names(
            field_names=item.uses_form_fields or [],
            runtime_input_type=primary_runtime_input_type,
        )
        dropped_field_names.extend(dropped)
        if filtered == (item.uses_form_fields or []):
            steps.append(item)
            continue
        steps.append(item.model_copy(update={"uses_form_fields": filtered}))
        changed = True

    if not changed:
        return proposal, dropped_field_names
    return proposal.model_copy(update={"steps": steps}), dropped_field_names


def _sanitize_shadowed_form_fields(
    *,
    proposal: MaterializedOrderedEditProposal,
    base_form_fields: list[FormFieldSpec] | None,
    primary_runtime_input_type: InputType | None,
) -> tuple[MaterializedOrderedEditProposal, list[str]]:
    if "form_fields" not in proposal.model_fields_set or proposal.form_fields is None:
        return proposal, []

    kept_fields: list[FormFieldSpec] = []
    dropped_field_names: list[str] = []
    for field in proposal.form_fields:
        if is_primary_runtime_input_shadow_field(
            variable_name=field.name,
            field_type=field.type,
            runtime_input_type=primary_runtime_input_type,
        ):
            if proposal.form_field_provenance.get(field.name) == "user_confirmed":
                raise AIBuilderArchitectureError(
                    public_code="architecture_materialization_failed",
                    repair_disposition="user_action",
                    detail=(
                        f"Confirmed runtime field '{field.name}' duplicates the "
                        "flow's primary runtime input."
                    ),
                    log_context={
                        "failure_code": "confirmed_form_field_incompatible",
                        "field_names": field.name,
                    },
                )
            dropped_field_names.append(field.name)
            continue
        kept_fields.append(field)

    if not dropped_field_names:
        return proposal, []
    if not kept_fields and not base_form_fields:
        return proposal.model_copy(update={"form_fields": None}), dropped_field_names
    return proposal.model_copy(
        update={"form_fields": kept_fields or None}
    ), dropped_field_names


def _repair_leading_audio_shape(
    *,
    proposal: MaterializedOrderedEditProposal,
    current_steps: list[FlowStep],
    warnings: list[str],
) -> MaterializedOrderedEditProposal:
    if len(proposal.steps) < 2 or not current_steps:
        return proposal
    if _starts_with_transcription_step(proposal.steps):
        return proposal

    current_by_ref = {
        existing_step_ref_for_order(step.step_order): step for step in current_steps
    }
    first_item = proposal.steps[0]
    if not isinstance(first_item, ModifyExistingStep):
        return proposal
    first_step = current_by_ref.get(first_item.existing_step_ref)
    if first_step is None:
        return proposal
    if not _is_bad_leading_audio_document_extraction(
        first_step,
        terminal_output_type=_terminal_output_type(proposal.steps, current_by_ref),
    ):
        return proposal

    transcript_step = MaterializedAddStep(
        step=NewStepDraft(
            name="Transkribera ljud",
            instructions="Transkribera uppladdat ljud till text.",
            input_source=InputSource.FLOW_INPUT,
            input_type=InputType.AUDIO,
            output_type=OutputType.TEXT,
            runtime_required=_runtime_input_required(first_step.input_config),
            runtime_max_files=_runtime_input_max_files(first_step.input_config),
        )
    )
    rewired_first = ModifyExistingStep.model_validate(
        {
            **first_item.model_dump(mode="python", exclude_unset=True),
            "input_source": InputSource.PREVIOUS_STEP,
            "input_type": InputType.TEXT,
        }
    )
    warnings.append(
        "Inserted a dedicated audio transcription step before the existing "
        "structured analysis step."
    )
    return proposal.model_copy(
        update={"steps": [transcript_step, rewired_first, *proposal.steps[1:]]}
    )


def _starts_with_transcription_step(
    steps: list[MaterializedOrderedEditStep],
) -> bool:
    first = steps[0]
    return (
        isinstance(first, MaterializedAddStep)
        and first.step.input_source == InputSource.FLOW_INPUT
        and first.step.input_type == InputType.AUDIO
        and first.step.output_type == OutputType.TEXT
    )


def _terminal_output_type(
    steps: list[MaterializedOrderedEditStep],
    current_by_ref: dict[str, FlowStep],
) -> OutputType | None:
    terminal = steps[-1]
    if isinstance(terminal, MaterializedAddStep):
        return terminal.step.output_type
    if "output_type" in terminal.model_fields_set and terminal.output_type is not None:
        return terminal.output_type
    current = current_by_ref.get(terminal.existing_step_ref)
    if current is None:
        return None
    try:
        return OutputType(current.output_type)
    except ValueError:
        return None


def _is_bad_leading_audio_document_extraction(
    step: FlowStep,
    *,
    terminal_output_type: OutputType | None,
) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT.value
        and step.input_type == InputType.AUDIO.value
        and step.output_type != OutputType.TEXT.value
        and terminal_output_type in {OutputType.DOCX, OutputType.PDF}
    )


def _build_form_field_changes(
    current_fields: list[FormFieldSpec] | None,
    proposed_fields: list[FormFieldSpec] | None,
) -> list[FormFieldChange]:
    current_by_name = {field.name: field for field in current_fields or []}
    proposed_by_name = {field.name: field for field in proposed_fields or []}
    changes: list[FormFieldChange] = []

    for field in proposed_fields or []:
        current = current_by_name.get(field.name)
        if current is None:
            changes.append(FormFieldChange(kind="added", field_name=field.name))
        elif current != field:
            changes.append(FormFieldChange(kind="modified", field_name=field.name))

    for field in current_fields or []:
        if field.name not in proposed_by_name:
            changes.append(FormFieldChange(kind="removed", field_name=field.name))

    return changes


def _runtime_input_required(input_config: dict[str, Any] | None) -> bool:
    runtime_input = _runtime_input_config(input_config)
    if isinstance(runtime_input.get("required"), bool):
        return cast(bool, runtime_input["required"])
    return True


def _runtime_input_max_files(input_config: dict[str, Any] | None) -> int | None:
    runtime_input = _runtime_input_config(input_config)
    max_files = runtime_input.get("max_files")
    return max_files if isinstance(max_files, int) else None


def _mapped_file_limit_policy_advisories(
    *,
    current_steps: list[FlowStep],
    mapped_execution_policy: FlowMappedExecutionPolicy | None,
) -> list[EditAdvisory]:
    policy_limit = (
        mapped_execution_policy.max_provider_calls_per_mapped_step
        if mapped_execution_policy is not None
        else None
    )
    if policy_limit is None:
        return []
    authored_limits = [
        limit
        for step in current_steps
        if (limit := _runtime_input_max_files(step.input_config)) is not None
        and limit > policy_limit
    ]
    if not authored_limits:
        return []
    return [
        EditAdvisory(
            code="mapped_file_limit_exceeds_policy",
            message=(
                "The authored mapped file ceiling exceeds the current organization "
                "policy. It is preserved and must be reviewed explicitly."
            ),
            severity="warning",
            field="steps.runtime_input.max_files",
        )
    ]


def _runtime_input_config(input_config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(input_config, dict):
        return {}
    runtime_input = input_config.get("runtime_input")
    return (
        cast(dict[str, Any], runtime_input) if isinstance(runtime_input, dict) else {}
    )


def _build_normalization_advisories(
    normalization_changes: list[tuple[StepSpec, StepNormalizationChange]],
) -> list[EditAdvisory]:
    advisories: list[EditAdvisory] = []
    for step, change in normalization_changes:
        step_ref = step.existing_step_ref or step.plan_step_ref
        advisories.append(
            EditAdvisory(
                code=change.code,
                message=change.message,
                severity=change.severity,
                field=f"{step_ref}.{change.field_suffix}",
            )
        )
    return advisories


def _build_step_changes(
    *,
    base_spec: FlowDraftSpecCore,
    compiled_steps: list[StepSpec],
    removed_refs: frozenset[str],
) -> list[StepChange]:
    existing_order_to_plan_ref = {
        existing_order: step.plan_step_ref
        for step in compiled_steps
        if (
            (existing_order := existing_step_order_from_ref(step.existing_step_ref))
            is not None
        )
    }
    removed_names: dict[str, str] = {}
    baseline_steps: list[StepSpec] = []
    for step in base_spec.steps:
        if step.existing_step_ref is None:
            continue
        baseline_steps.append(
            _canonicalize_step_for_diff(
                _restamp_existing_step_plan_ref_for_diff(
                    step,
                    existing_order_to_plan_ref,
                ),
                existing_order_to_plan_ref,
            )
        )
        removed_names[step.existing_step_ref] = step.name
    baseline_specs = _normalize_baseline_specs_for_diff(baseline_steps)

    # Binding refs are plan-local bookkeeping; the change list names the step.
    step_names = {step.plan_step_ref: step.name for step in compiled_steps}

    def step_label(ref: str) -> str:
        return step_names.get(ref, ref)

    step_changes: list[StepChange] = []
    for step in compiled_steps:
        if step.existing_step_ref is None:
            step_changes.append(
                StepChange(
                    kind="added",
                    step_name=step.name,
                    step_ref=None,
                )
            )
            continue

        previous = baseline_specs.get(step.existing_step_ref)
        if previous is None:
            # Existing steps are compiled from the published baseline and their
            # coverage is validated before this point; a missing one here is
            # compiler corruption, and a diff that hid it would approve it.
            raise AIBuilderArchitectureError(
                public_code="architecture_materialization_failed",
                repair_disposition="server_defect",
                detail=(
                    "Compiled existing step has no published baseline to diff "
                    f"against: {step.existing_step_ref}"
                ),
                log_context={"failure_code": "step_diff_missing_baseline"},
            )
        field_changes = _step_field_changes(previous, step, step_label=step_label)
        step_changes.append(
            StepChange(
                kind="modified" if field_changes else "unchanged",
                step_name=step.name,
                step_ref=step.existing_step_ref,
                field_changes=field_changes,
            )
        )

    for step in base_spec.steps:
        ref = step.existing_step_ref
        if ref is None or ref not in removed_refs:
            continue
        step_changes.append(
            StepChange(
                kind="removed",
                step_name=removed_names[ref],
                step_ref=ref,
            )
        )
    return step_changes


def _canonicalize_step_for_diff(
    step: StepSpec,
    existing_order_to_plan_ref: dict[int, str],
) -> StepSpec:
    return _rewrite_runtime_aliases_for_existing_step(
        step,
        existing_order_to_plan_ref,
    )


def _restamp_existing_step_plan_ref_for_diff(
    step: StepSpec,
    existing_order_to_plan_ref: dict[int, str],
) -> StepSpec:
    existing_order = existing_step_order_from_ref(step.existing_step_ref)
    if existing_order is None:
        return step
    plan_ref = existing_order_to_plan_ref.get(existing_order)
    if plan_ref is None or plan_ref == step.plan_step_ref:
        return step
    return step.model_copy(update={"plan_step_ref": plan_ref})


def _normalize_baseline_specs_for_diff(steps: list[StepSpec]) -> dict[str, StepSpec]:
    normalized_spec, _ = normalize_ai_builder_spec(
        FlowDraftSpecCore(flow_name="Existing flow", steps=steps, form_fields=None)
    )
    return {
        step.existing_step_ref: step
        for step in normalized_spec.steps
        if step.existing_step_ref is not None
    }


def _comparable_step_payload(step: StepSpec) -> dict[str, Any]:
    payload = step.model_dump(mode="json")
    payload.pop("plan_step_ref", None)
    payload.pop("existing_step_ref", None)
    return payload


# Every comparable field of a step, in reading order. The assistant spec is
# read as its three parts. A StepSpec field missing here fails loudly below,
# so a new field can never change a step without being explained.
_STEP_CHANGE_FIELDS: tuple[StepChangeField, ...] = (
    "name",
    "instructions",
    "model_ref",
    "knowledge_refs",
    "input_source",
    "input_type",
    "input_bindings",
    "input_contract",
    "input_config",
    "output_mode",
    "output_type",
    "output_contract",
    "output_config",
    "review_policy",
)
_ASSISTANT_SPEC_FIELDS: tuple[StepChangeField, ...] = (
    "instructions",
    "model_ref",
    "knowledge_refs",
)


def _step_field_changes(
    previous: StepSpec, current: StepSpec, *, step_label: Callable[[str], str]
) -> list[StepFieldChange]:
    """What differs between the published step and the proposal, field by field.

    This is the one comparison that decides whether a step is modified: the
    step is unchanged exactly when this list is empty, so an "updated" badge
    always has something to show, and every row shows two different values.
    """

    before = _comparable_step_payload(previous)
    after = _comparable_step_payload(current)
    before_spec = cast(dict[str, Any], before.pop("assistant_spec"))
    after_spec = cast(dict[str, Any], after.pop("assistant_spec"))
    unaccounted = (set(before) | set(after)) - set(_STEP_CHANGE_FIELDS)
    unaccounted |= (set(before_spec) | set(after_spec)) - set(_ASSISTANT_SPEC_FIELDS)
    if unaccounted:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            repair_disposition="server_defect",
            detail=(
                "StepSpec fields without a change explanation: "
                + ", ".join(sorted(unaccounted))
            ),
            log_context={"failure_code": "step_diff_unexplained_field"},
        )
    changes: list[StepFieldChange] = []
    for field in _STEP_CHANGE_FIELDS:
        source_before, source_after = (
            (before_spec, after_spec)
            if field in _ASSISTANT_SPEC_FIELDS
            else (before, after)
        )
        value_before = source_before.get(field)
        value_after = source_after.get(field)
        # Equality is JSON equality: Python reads True and 1 as equal, a JSON
        # schema does not, and a schema is exactly what these values may be.
        if canonical_json_bytes(value_before) == canonical_json_bytes(value_after):
            continue
        changes.append(
            StepFieldChange(
                field=field,
                previous=_readable_field_value(field, value_before, step_label),
                current=_readable_field_value(field, value_after, step_label),
                previous_detail=_detail_field_value(value_before),
                current_detail=_detail_field_value(value_after),
            )
        )
    return changes


def _readable_field_value(
    field: StepChangeField, value: Any, step_label: Callable[[str], str]
) -> str | None:
    """The value as the plan can show it; None reads as "none" on screen.

    Values are data, not prose: names, field paths, the question a step asks,
    a mode. The screen owns the words around them.
    """

    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        items = cast(list[Any], value)
        return ", ".join(str(item) for item in items) or None
    if isinstance(value, dict):
        payload = cast(dict[str, Any], value)
        if field in ("input_contract", "output_contract"):
            # The short reading is the set of fields: a reordered schema is
            # "ändrad" with the whole value behind the fold, not two long lists.
            return ", ".join(sorted(schema_leaf_property_names(payload))) or None
        if field == "input_bindings":
            refs = source_ref_bindings(payload)
            if refs:
                return ", ".join(
                    step_label(ref.step_ref)
                    + ("." + ".".join(ref.field_path) if ref.field_path else "")
                    for ref in refs
                )
            return question_binding(payload)
        if field == "review_policy":
            mode = payload.get("mode")
            return str(mode) if mode is not None else None
        return _detail_field_value(payload)
    return str(value)


def _detail_field_value(value: Any) -> str | None:
    """The complete value of a structured field, in the canonical encoding."""

    if not isinstance(value, (dict, list)):
        return None
    payload = cast(dict[str, Any] | list[Any], value)
    return canonical_json_bytes(payload).decode("utf-8")


def _compute_confidence(
    *,
    step_changes: list[StepChange],
    form_changes: list[FormFieldChange],
    warnings: list[str],
) -> EditConfidence:
    if warnings:
        return "needs_review"
    changed_count = sum(
        1 for change in step_changes if change.kind in {"added", "modified", "removed"}
    ) + len(form_changes)
    if changed_count > 5:
        return "needs_review"
    return "ready"


def _build_description_advisories(
    *,
    proposal: MaterializedOrderedEditProposal,
    base_spec: FlowDraftSpecCore,
    compiled_steps: list[StepSpec],
    current_description: str | None,
) -> list[EditAdvisory]:
    """Emit advisory when semantic signature changed but description wasn't updated."""
    if "flow_description" in proposal.model_fields_set:
        return []
    if not base_spec.steps or not compiled_steps or not current_description:
        return []

    old_sig = FlowSemanticSignature.from_steps(base_spec.steps)
    new_sig = FlowSemanticSignature.from_steps(compiled_steps)

    if not old_sig.has_semantic_change(new_sig):
        return []

    return [
        EditAdvisory(
            code="flow_description_update_required",
            message=(
                "Flow inputs or outputs changed but the description was not updated. "
                "Consider updating the description to reflect the new behavior."
            ),
            severity="warning",
            field="flow_description",
        )
    ]


def _build_primary_input_shadow_advisories(
    *,
    field_names: list[str],
    primary_runtime_input_type: InputType | None,
    field_provenance: dict[str, FlowInputFieldProvenance],
) -> list[EditAdvisory]:
    unique_names = sorted(set(field_names))
    if not unique_names or primary_runtime_input_type is None:
        return []
    joined_names = ", ".join(f"'{name}'" for name in unique_names)
    return [
        EditAdvisory(
            code="form_field_shadows_primary_input",
            message=(
                f"Ignored form field reference(s) {joined_names} because "
                f"the flow's primary {primary_runtime_input_type.value} input is "
                "already provided through Flow input, not an inmatningsfält."
            ),
            severity="info",
            field="form_fields",
            field_provenance=(
                field_provenance.get(unique_names[0], "model_proposed")
                if len(unique_names) == 1
                else None
            ),
        )
    ]


def _primary_runtime_input_type_from_steps(
    steps: list[FlowStep],
) -> InputType | None:
    for step in sorted(steps, key=lambda item: item.step_order):
        if step.input_source != InputSource.FLOW_INPUT.value:
            continue
        try:
            return InputType(step.input_type)
        except ValueError:
            return None
    return None


def _primary_runtime_required_from_steps(steps: list[FlowStep]) -> bool:
    if not steps:
        return True
    first_step = min(steps, key=lambda item: item.step_order)
    if first_step.input_source != InputSource.FLOW_INPUT.value:
        return True
    return _runtime_input_required(first_step.input_config)


def _without_primary_runtime_shadow_fields(
    step: NewStepDraft,
    *,
    primary_runtime_input_type: InputType | None,
) -> tuple[NewStepDraft, list[str]]:
    filtered, dropped = split_primary_runtime_input_shadow_names(
        field_names=step.uses_form_fields,
        runtime_input_type=primary_runtime_input_type,
    )
    if filtered == step.uses_form_fields:
        return step, dropped
    return step.model_copy(update={"uses_form_fields": filtered}), dropped


def _canonicalize_existing_runtime_aliases(
    step_specs: list[StepSpec],
) -> list[StepSpec]:
    existing_order_to_plan_ref = {
        existing_order: step.plan_step_ref
        for step in step_specs
        if (
            (existing_order := existing_step_order_from_ref(step.existing_step_ref))
            is not None
        )
    }
    if not existing_order_to_plan_ref:
        return step_specs

    return [
        _rewrite_runtime_aliases_for_existing_step(step, existing_order_to_plan_ref)
        for step in step_specs
    ]


def _rewrite_runtime_aliases_for_existing_step(
    step: StepSpec,
    existing_order_to_plan_ref: dict[int, str],
) -> StepSpec:
    if step.existing_step_ref is None:
        return step

    updates: dict[str, Any] = {}
    rewritten_instructions = _rewrite_runtime_alias_string(
        step.assistant_spec.instructions,
        existing_order_to_plan_ref,
    )
    if rewritten_instructions != step.assistant_spec.instructions:
        updates["assistant_spec"] = step.assistant_spec.model_copy(
            update={"instructions": rewritten_instructions}
        )

    if step.input_bindings is not None:
        rewritten_bindings = _rewrite_source_ref_step_aliases(
            _rewrite_runtime_alias_value(
                step.input_bindings,
                existing_order_to_plan_ref,
            ),
            existing_order_to_plan_ref,
        )
        if rewritten_bindings != step.input_bindings:
            updates["input_bindings"] = rewritten_bindings

    if step.output_config is not None:
        rewritten_output_config = _rewrite_runtime_alias_value(
            step.output_config,
            existing_order_to_plan_ref,
        )
        if rewritten_output_config != step.output_config:
            updates["output_config"] = rewritten_output_config

    return step.model_copy(update=updates) if updates else step


def _rewrite_runtime_alias_value(
    value: Any,
    existing_order_to_plan_ref: dict[int, str],
) -> Any:
    if isinstance(value, str):
        return _rewrite_runtime_alias_string(value, existing_order_to_plan_ref)
    if isinstance(value, dict):
        return {
            key: _rewrite_runtime_alias_value(inner, existing_order_to_plan_ref)
            for key, inner in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [
            _rewrite_runtime_alias_value(item, existing_order_to_plan_ref)
            for item in cast(list[Any], value)
        ]
    return value


def _rewrite_source_ref_step_aliases(
    input_bindings: Any,
    existing_order_to_plan_ref: dict[int, str],
) -> Any:
    # A persisted source_refs entry names its producer by runtime alias
    # ("step_2") in its `step_ref` value, not in a template. The compiled spec
    # names steps by plan ref and every reader of it (critics, projection
    # completion) resolves plan refs only, so an untouched step's refs must
    # move with the templates (2026-09-05). Only this structure is a
    # reference: a placeholder elsewhere may be called "step_ref" too.
    if not isinstance(input_bindings, dict):
        return input_bindings
    bindings = cast(dict[str, Any], input_bindings)
    raw_refs = bindings.get(SOURCE_REFS_BINDING_KEY)
    if not isinstance(raw_refs, list):
        return bindings
    rewritten_refs: list[Any] = []
    for raw_ref in cast(list[Any], raw_refs):
        if not isinstance(raw_ref, dict):
            rewritten_refs.append(raw_ref)
            continue
        ref = cast(dict[str, Any], raw_ref)
        step_ref = ref.get("step_ref")
        match = (
            _RUNTIME_STEP_REF_PATTERN.match(step_ref)
            if isinstance(step_ref, str)
            else None
        )
        plan_ref = (
            existing_order_to_plan_ref.get(int(match.group(1)))
            if match is not None
            else None
        )
        rewritten_refs.append({**ref, "step_ref": plan_ref} if plan_ref else ref)
    if rewritten_refs == raw_refs:
        return bindings
    return {**bindings, SOURCE_REFS_BINDING_KEY: rewritten_refs}


def _rewrite_runtime_alias_string(
    text: str,
    existing_order_to_plan_ref: dict[int, str],
) -> str:
    def _replace(match: re.Match[str]) -> str:
        old_order = int(match.group(1))
        plan_ref = existing_order_to_plan_ref.get(old_order)
        if plan_ref is None:
            return match.group(0)
        return "{{ " + plan_ref + match.group(2) + " }}"

    return _RUNTIME_STEP_ALIAS_PATTERN.sub(_replace, text)
