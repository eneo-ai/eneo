"""Ordered edit compiler for the AI Builder.

Compiles the model-visible ordered edit proposal into the canonical authoring
spec plus the edit approval metadata the user approves. The key principle is
that every existing step is either represented in order or explicitly removed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_authoring_projection import (
    MaterializedAddStep,
    MaterializedOrderedEditProposal,
    MaterializedOrderedEditStep,
    compile_ordered_edit_proposal,
    edit_baseline_spec,
    input_restates_exactly,
    materialize_ordered_edit_proposal,
    question_form_reads,
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
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_flow_schema_values import FlowInputFieldProvenance
from eneo.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import make_plan_step_ref
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
)
from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    dropped_primary_field_names,
    elect_main_text_field,
    main_text_is_a_field,
    split_primary_runtime_input_shadow_names,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ModifyExistingStep,
    OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_DIAGNOSTIC_NAME_LENGTH,
    MAX_DIAGNOSTIC_NAMES,
    BoundedListing,
    display_value,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from eneo.flows.ai_builder.ai_builder_step_reads import (
    form_fields_read,
    spec_step_refs,
    step_output_channel,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    StepNormalizationChange,
    discarded_output_config_keys,
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
from eneo.flows.application.flow_authoring_snapshot import (
    current_flow_authoring_spec,
    flow_step_to_authoring_spec,
)
from eneo.flows.application.flow_draft_materialization import (
    validate_existing_step_ref_coverage,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_authoring_variable_rewriting import (
    rewrite_config_sites,
    rewrite_step_alias_heads,
)
from eneo.flows.input_binding_contract_rules import (
    SOURCE_REFS_BINDING_KEY,
    question_binding,
    source_ref_bindings,
    source_ref_step_order,
)
from eneo.flows.step_lineage import (
    existing_step_order_from_ref,
    existing_step_ref_for_order,
)


@dataclass(frozen=True, slots=True)
class _PreparedOrderedEditProposal:
    proposal: MaterializedOrderedEditProposal
    warnings: list[str]
    shadowed_primary_input_fields: list[str]
    form_field_provenance: dict[str, FlowInputFieldProvenance]
    # The run form's one main-text field when the run collects other fields.
    main_text_field: str | None = None


@dataclass(frozen=True, slots=True)
class EditMutationScope:
    """The saved steps a step-scoped edit leaves exactly as saved.

    A saved-step revision may change the selected step and nothing else.
    Every other step is protected: it leaves compilation and session
    preparation as the saved revision holds it, `plan_step_ref` excepted
    (positional, stamped by the compiler). The normalizers, the template
    contract and resource canonicalization run over the whole spec and know
    nothing of the scope; this one owner re-imposes it after each of them,
    and the scoped revision guard checks the outcome after final
    preparation. A normalization change on a protected step is therefore
    never reported: it did not happen.
    """

    protected_steps: Mapping[str, StepSpec]
    # Every saved step by ref, the baseline a compiled step is judged against.
    saved_steps: Mapping[str, StepSpec]

    def is_protected(self, step: StepSpec) -> bool:
        return step.existing_step_ref in self.protected_steps

    def protecting_unchanged(self, compiled_steps: list[StepSpec]) -> EditMutationScope:
        """Also protect every authored step whose compiled form equals the
        saved one: a repeated saved value is not a change, and the
        normalizers must not turn it into one."""

        unchanged = {
            step.existing_step_ref: prior
            for step in compiled_steps
            if step.existing_step_ref is not None
            and not self.is_protected(step)
            and (prior := self.saved_steps.get(step.existing_step_ref)) is not None
            and _authoring_payload(step) == _authoring_payload(prior)
        }
        if not unchanged:
            return self
        return EditMutationScope(
            protected_steps={**self.protected_steps, **unchanged},
            saved_steps=self.saved_steps,
        )

    def restore(self, spec: FlowDraftSpecCore) -> FlowDraftSpecCore:
        steps = [
            self.protected_steps[step.existing_step_ref].model_copy(
                update={"plan_step_ref": step.plan_step_ref}
            )
            if step.existing_step_ref is not None and self.is_protected(step)
            else step
            for step in spec.steps
        ]
        if steps == spec.steps:
            return spec
        return spec.model_copy(update={"steps": steps})


@dataclass(frozen=True, slots=True)
class EditCompilationResult:
    spec: FlowDraftSpecCore
    # The approval of what the model authored, read before session
    # preparation: it bounds the authored effect. The user approves the one
    # from approval_for_prepared_spec, never this one.
    authored_approval: FlowBuilderEditApproval
    # The published flow both approvals' diffs read against.
    base_spec: FlowDraftSpecCore
    # Set for a saved-step revision; session preparation applies it too.
    mutation_scope: EditMutationScope | None = None

    def approval_for_prepared_spec(
        self, prepared_spec: FlowDraftSpecCore
    ) -> FlowBuilderEditApproval:
        """The approval whose diff describes ``prepared_spec``.

        Session preparation rewrites the compiled spec after this compiler
        has run (duplicate step names, resource canonicalisation, terminal
        output alignment), so the diff the user approves is read again from
        the same baseline against the spec that is actually returned.
        """

        step_changes = build_step_changes(
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
    inherited_template_asset_id: UUID | None = None,
    revision_spec: FlowDraftSpecCore | None = None,
) -> EditCompilationResult:
    """Compile an ordered edit proposal into a concrete flow preview + diff."""
    primary_runtime_input_type = (
        requested_primary_runtime_input_type
        or _primary_runtime_input_type_from_steps(current_steps)
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
    if revision_spec is not None and [
        step.existing_step_ref for step in revision_spec.steps
    ] != [step.existing_step_ref for step in base_spec.steps]:
        raise AIBuilderBadRequestException(
            "The revision must preserve the saved step sequence.",
            code=AIBuilderErrorCode.BAD_REQUEST,
        )
    mutation_scope: EditMutationScope | None = None
    if revision_spec is not None:
        proposal, mutation_scope = _expand_saved_step_proposal(
            proposal, revision_spec=revision_spec
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
    baseline = edit_baseline_spec(saved=base_spec, revision=revision_spec)
    prepared = _prepare_ordered_edit_proposal(
        proposal=materialized_proposal,
        current_steps=current_steps,
        baseline_form_fields=baseline.form_fields,
        primary_runtime_input_type=primary_runtime_input_type,
        may_restructure=mutation_scope is None,
    )
    compiled_spec = compile_ordered_edit_proposal(
        base_spec=baseline,
        proposal=prepared.proposal,
        ui_language=ui_language,
    )
    compiled_steps = compiled_spec.steps

    compiled_steps = _canonicalize_existing_runtime_aliases(
        compiled_steps,
        saved_step_names={
            step.step_order: step.user_description
            for step in current_steps
            if step.user_description
        },
        template_contract_runs=selected_template_count is not None,
    )
    if mutation_scope is not None:
        mutation_scope = mutation_scope.protecting_unchanged(compiled_steps)
    inherited_template_bindings = _inherited_template_bindings(
        current_steps,
        existing_order_to_plan_ref=_existing_order_to_plan_ref(compiled_steps),
    )
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
            # An edit keeps the mappings the flow already has; only a
            # placeholder without one is derived.
            existing_bindings=inherited_template_bindings,
            inherited_template_asset_id=inherited_template_asset_id,
            # A saved step and a step the edit adds are the user's to remove.
            drop_unused_predecessor=False,
            is_frozen=mutation_scope.is_protected if mutation_scope else None,
        )
    if mutation_scope is not None:
        normalization_changes = [
            (step, change)
            for step, change in normalization_changes
            if not mutation_scope.is_protected(step)
        ]
        normalized_spec = mutation_scope.restore(normalized_spec)
    # The one place the run form is judged: on the final spec, so a read or a
    # field added by the proposal, by normalization or by the template
    # attachment is seen, and the form diff below shows what changed.
    normalized_spec = _settle_run_form(
        normalized_spec,
        baseline=baseline,
        main_text_field=prepared.main_text_field,
        scoped=mutation_scope is not None,
    )
    compiled_steps = normalized_spec.steps
    final_name = normalized_spec.flow_name
    final_description = normalized_spec.flow_description
    compiled_form_fields = normalized_spec.form_fields
    # The diff is against the SAVED flow's fields (base_form_fields, from its
    # metadata): that is the form the person has now and approves a change to.
    # Every stage above judges against the edit baseline instead.
    form_changes = build_form_field_changes(base_form_fields, compiled_form_fields)

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

    step_changes = build_step_changes(
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
        mutation_scope=mutation_scope,
    )


def _expand_saved_step_proposal(
    proposal: OrderedEditProposal,
    *,
    revision_spec: FlowDraftSpecCore,
) -> tuple[OrderedEditProposal, EditMutationScope]:
    """Fill the saved steps the fragment left out and protect every step the
    model did not author a change on (an identity-only entry included)."""

    modifications: list[ModifyExistingStep] = []
    for step in proposal.steps:
        if not isinstance(step, ModifyExistingStep):
            raise AIBuilderBadRequestException(
                "A selected-step edit must not add steps.",
                code=AIBuilderErrorCode.BAD_REQUEST,
            )
        modifications.append(step)
    current_refs = [
        step.existing_step_ref
        for step in revision_spec.steps
        if step.existing_step_ref is not None
    ]
    submitted_refs = [step.existing_step_ref for step in modifications]
    submitted_ref_set = set(submitted_refs)
    validate_existing_step_ref_coverage(
        current_refs=set(current_refs),
        preserved_refs=[
            *submitted_refs,
            *(ref for ref in current_refs if ref not in submitted_ref_set),
        ],
        removed_existing_step_refs=proposal.removed_existing_step_refs,
    )
    by_ref = {step.existing_step_ref: step for step in modifications}
    expanded = proposal.model_copy(
        update={
            "steps": [
                by_ref[ref]
                if ref in by_ref
                else ModifyExistingStep(existing_step_ref=ref)
                for ref in current_refs
            ]
        }
    )
    authored_refs = {
        step.existing_step_ref for step in modifications if step.authored_fields
    }
    saved_steps = {
        step.existing_step_ref: step
        for step in revision_spec.steps
        if step.existing_step_ref is not None
    }
    return expanded, EditMutationScope(
        protected_steps={
            ref: step for ref, step in saved_steps.items() if ref not in authored_refs
        },
        saved_steps=saved_steps,
    )


def _authoring_payload(step: StepSpec) -> dict[str, Any]:
    return step.model_dump(mode="json", exclude={"plan_step_ref"})


def _prepare_ordered_edit_proposal(
    *,
    proposal: MaterializedOrderedEditProposal,
    current_steps: list[FlowStep],
    baseline_form_fields: list[FormFieldSpec] | None,
    primary_runtime_input_type: InputType | None,
    may_restructure: bool,
) -> _PreparedOrderedEditProposal:
    warnings: list[str] = []
    base_form_fields = baseline_form_fields
    edited_fields = (
        proposal.form_fields
        if "form_fields" in proposal.model_fields_set
        else base_form_fields
    ) or []
    declared = [(field.name, field.type) for field in edited_fields]
    dropped = dropped_primary_field_names(
        runtime_input_type=primary_runtime_input_type, fields=declared
    )
    elected = (
        elect_main_text_field(declared)
        if main_text_is_a_field(
            runtime_input_type=primary_runtime_input_type, fields=declared
        )
        else None
    )
    if elected is not None:
        # The run collects other fields, so the main text is a field: the one
        # elected is required. Every other field keeps its declared contract.
        proposal = _with_main_text_field_required(proposal, elected)
    # A read of a shadow-looking name no field declares is still the shadow it was.
    kept_names = frozenset(name for name, _ in declared) - dropped
    prepared, dropped_step_field_names = _sanitize_shadowed_primary_inputs(
        proposal=proposal,
        primary_runtime_input_type=primary_runtime_input_type,
        kept_names=kept_names,
    )
    prepared, dropped_declared_field_names = _sanitize_shadowed_form_fields(
        proposal=prepared,
        base_form_fields=base_form_fields,
        primary_runtime_input_type=primary_runtime_input_type,
        dropped_names=dropped,
    )
    if may_restructure:
        # A saved-step revision keeps the saved step sequence; inserting a
        # transcription step is a whole-flow edit.
        prepared = _repair_leading_audio_shape(
            proposal=prepared,
            current_steps=current_steps,
            form_field_names=[
                field.name
                for field in (
                    prepared.form_fields
                    if "form_fields" in prepared.model_fields_set
                    else base_form_fields
                )
                or []
            ],
            saved_form_field_names=[field.name for field in base_form_fields or []],
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
        main_text_field=elected,
    )


def _with_main_text_field_required(
    proposal: MaterializedOrderedEditProposal, elected: str
) -> MaterializedOrderedEditProposal:
    if "form_fields" not in proposal.model_fields_set or not proposal.form_fields:
        return proposal
    return proposal.model_copy(
        update={
            "form_fields": [
                field.model_copy(update={"required": True})
                if field.name == elected
                else field
                for field in proposal.form_fields
            ]
        }
    )


def _settle_run_form(
    compiled: FlowDraftSpecCore,
    *,
    baseline: FlowDraftSpecCore,
    main_text_field: str | None,
    scoped: bool,
) -> FlowDraftSpecCore:
    """The run form an edit ends with, judged once on the final spec.

    A whole-flow edit may change the run form: the main-text field it newly
    binds is required (see `_with_bound_main_text_required`) and the change
    shows in the form diff. A saved-step (`scoped`) edit may not change the run
    form in any way, so the rule is general: fields that differ from the
    baseline, whatever made them differ (a bind, a template placeholder), are
    refused with the whole-flow edit as the remedy."""

    settled = _with_bound_main_text_required(
        compiled, baseline=baseline, main_text_field=main_text_field
    )
    if not scoped:
        return settled
    baseline_fields = baseline.form_fields or []
    if (settled.form_fields or []) == baseline_fields:
        return settled
    raise AIBuilderBadRequestException(
        "A single-step edit cannot change the run form, and this edit would: "
        f"{_describe_form_change(baseline_fields, settled.form_fields or [])}. Leave "
        "out what causes it, such as a read of a form field the run form lets "
        "stay empty or a template placeholder the flow does not collect; the "
        "change itself is a whole-flow edit.",
        code=AIBuilderErrorCode.BAD_REQUEST,
    )


def _describe_form_change(
    saved: list[FormFieldSpec], final: list[FormFieldSpec]
) -> str:
    saved_by_name = {field.name: field for field in saved}
    final_names = {field.name for field in final}
    parts: list[str] = []
    for field in final:
        name = f"`{display_value(field.name)}`"
        before = saved_by_name.get(field.name)
        if before is None:
            parts.append(f"add {name}")
        elif before.model_copy(update={"required": field.required}) != field:
            parts.append(f"change {name}")
        elif before.required != field.required:
            parts.append(f"make {name} {'required' if field.required else 'optional'}")
    parts.extend(
        f"remove `{display_value(field.name)}`"
        for field in saved
        if field.name not in final_names
    )
    return ", ".join(parts) or "reorder the fields"


def _with_bound_main_text_required(
    compiled: FlowDraftSpecCore,
    *,
    baseline: FlowDraftSpecCore,
    main_text_field: str | None,
) -> FlowDraftSpecCore:
    """The main-text field an edit newly binds is required in the run form.

    A proposal that declares the form fields already has it required; one that
    omits them inherits the baseline fields, where it may be optional, so a step
    the edit newly makes read it would get an empty main text."""

    fields = compiled.form_fields or []
    field = next((item for item in fields if item.name == main_text_field), None)
    if main_text_field is None or field is None or field.required:
        return compiled
    saved_names = {item.name for item in baseline.form_fields or []}
    saved_refs = spec_step_refs(baseline.steps)
    saved_reads = {
        step.existing_step_ref: form_fields_read(
            step, order=order, step_refs=saved_refs, form_field_names=saved_names
        )
        for order, step in enumerate(baseline.steps, 1)
        if step.existing_step_ref is not None
    }
    names = {item.name for item in fields}
    refs = spec_step_refs(compiled.steps)
    for order, step in enumerate(compiled.steps, 1):
        reads = form_fields_read(
            step, order=order, step_refs=refs, form_field_names=names
        )
        if main_text_field not in reads:
            continue
        if main_text_field in saved_reads.get(step.existing_step_ref or "", ()):
            continue
        return compiled.model_copy(
            update={
                "form_fields": [
                    item.model_copy(update={"required": True})
                    if item.name == main_text_field
                    else item
                    for item in fields
                ]
            }
        )
    return compiled


def _sanitize_shadowed_primary_inputs(
    *,
    proposal: MaterializedOrderedEditProposal,
    primary_runtime_input_type: InputType | None,
    kept_names: frozenset[str] = frozenset(),
) -> tuple[MaterializedOrderedEditProposal, list[str]]:
    steps: list[MaterializedOrderedEditStep] = []
    dropped_field_names: list[str] = []
    changed = False

    for item in proposal.steps:
        if isinstance(item, MaterializedAddStep):
            step, dropped = _without_primary_runtime_shadow_fields(
                item.step,
                primary_runtime_input_type=primary_runtime_input_type,
                kept_names=kept_names,
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
            kept_names=kept_names,
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
    dropped_names: frozenset[str] = frozenset(),
) -> tuple[MaterializedOrderedEditProposal, list[str]]:
    if (
        "form_fields" not in proposal.model_fields_set
        or proposal.form_fields is None
        or primary_runtime_input_type is None
    ):
        return proposal, []

    kept_fields: list[FormFieldSpec] = []
    dropped_field_names: list[str] = []
    for field in proposal.form_fields:
        if field.name in dropped_names:
            dropped_field_names.append(field.name)
            continue
        kept_fields.append(field)

    confirmed = [
        name
        for name in dropped_field_names
        if proposal.form_field_provenance.get(name) == "user_confirmed"
    ]
    if confirmed:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            repair_disposition="user_action",
            detail="Confirmed runtime fields duplicate the flow's primary runtime input.",
            log_context={
                "failure_code": "confirmed_form_field_incompatible",
                "field_names": ", ".join(
                    name[:MAX_DIAGNOSTIC_NAME_LENGTH]
                    for name in confirmed[:MAX_DIAGNOSTIC_NAMES]
                ),
                "field_names_remaining": max(0, len(confirmed) - MAX_DIAGNOSTIC_NAMES),
                "runtime_input_type": primary_runtime_input_type.value,
            },
            affected=confirmed,
        )
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
    form_field_names: list[str],
    saved_form_field_names: list[str],
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

    # The rewired step reads the transcript through its lists, which must
    # restate its saved input exactly; a hand-written one only the user can
    # rewrite, and the model cannot undo a rewire it did not author.
    if not input_restates_exactly(
        flow_step_to_authoring_spec(first_step, first_item.existing_step_ref),
        prior_steps=[],
        form_field_names=saved_form_field_names,
    ):
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            repair_disposition="user_action",
            detail="The first step's own input cannot be rewired to the transcript.",
            log_context={"failure_code": "audio_repair_first_step_input_inexact"},
            affected=(first_step.user_description or first_item.existing_step_ref,),
        )
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
    # The rewired step reads the transcript instead of the upload; its form
    # reads stay, as authored or else as saved, and it reads no earlier step.
    rewired_first = ModifyExistingStep.model_validate(
        {
            "uses_form_fields": question_form_reads(
                first_step.input_bindings, form_field_names
            ),
            "uses_previous_fields": [],
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


def build_form_field_changes(
    current_fields: list[FormFieldSpec] | None,
    proposed_fields: list[FormFieldSpec] | None,
) -> list[FormFieldChange]:
    current_by_name = {field.name: field for field in current_fields or []}
    proposed_by_name = {field.name: field for field in proposed_fields or []}
    kept_before = [f.name for f in current_fields or [] if f.name in proposed_by_name]
    kept_now = [f.name for f in proposed_fields or [] if f.name in current_by_name]
    moved = {name for before, name in zip(kept_before, kept_now) if before != name}
    changes: list[FormFieldChange] = []

    for field in proposed_fields or []:
        current = current_by_name.get(field.name)
        if current is None:
            changes.append(FormFieldChange(kind="added", field_name=field.name))
            continue
        if current != field:
            changes.append(FormFieldChange(kind="modified", field_name=field.name))
        # A move is its own change, whether or not the field also changed.
        if field.name in moved:
            changes.append(
                FormFieldChange(kind="modified", field_name=field.name, details="moved")
            )

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


def build_step_changes(
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
    kept_names: frozenset[str] = frozenset(),
) -> tuple[NewStepDraft, list[str]]:
    filtered, dropped = split_primary_runtime_input_shadow_names(
        field_names=step.uses_form_fields,
        runtime_input_type=primary_runtime_input_type,
        kept_names=kept_names,
    )
    if filtered == step.uses_form_fields:
        return step, dropped
    return step.model_copy(update={"uses_form_fields": filtered}), dropped


def canonicalize_saved_revision_spec(spec: FlowDraftSpecCore) -> FlowDraftSpecCore:
    ref_mapping = {
        step.plan_step_ref: make_plan_step_ref(index)
        for index, step in enumerate(spec.steps)
    }
    steps = [
        step.model_copy(update={"plan_step_ref": ref_mapping[step.plan_step_ref]})
        for step in spec.steps
    ]
    return spec.model_copy(
        update={
            "steps": _canonicalize_existing_runtime_aliases(steps),
            "document_body_writer_step_refs": tuple(
                ref_mapping[ref] for ref in spec.document_body_writer_step_refs
            )
            if spec.document_body_writer_step_refs is not None
            else None,
        }
    )


def _existing_order_to_plan_ref(step_specs: list[StepSpec]) -> dict[int, str]:
    return {
        existing_order: step.plan_step_ref
        for step in step_specs
        if (
            (existing_order := existing_step_order_from_ref(step.existing_step_ref))
            is not None
        )
    }


def _inherited_template_bindings(
    current_steps: list[FlowStep],
    *,
    existing_order_to_plan_ref: dict[int, str],
) -> dict[str, str] | None:
    """The placeholder mappings the flow's terminal template step carries.

    Read off the persisted flow, not the proposal, so they survive an edit
    that moves the template-fill step; step aliases are rewritten to the plan
    refs of the steps that remain, like every other persisted reference.
    """

    if not current_steps:
        return None
    terminal = max(current_steps, key=lambda step: step.step_order)
    if terminal.output_mode != FlowOutputMode.TEMPLATE_FILL:
        return None
    raw = (terminal.output_config or {}).get("bindings")
    if not isinstance(raw, dict):
        return None
    bindings = {
        key: value
        for key, value in cast(dict[str, Any], raw).items()
        if isinstance(value, str)
    }
    # A persisted alias names its producer by the step order it had. Only a
    # step still in the plan is rewritten to a plan ref; an alias left in
    # "step_N" form names a removed producer, and the template contract
    # rejects it if the placeholder is retained, never by position.
    return cast(
        dict[str, str],
        _rewrite_runtime_alias_value(bindings, _resolve_by(existing_order_to_plan_ref)),
    )


# The plan ref a saved alias's order names now, given the alias as written.
AliasResolver = Callable[[int, str], str | None]


def _resolve_by(existing_order_to_plan_ref: Mapping[int, str]) -> AliasResolver:
    return lambda order, _expression: existing_order_to_plan_ref.get(order)


@dataclass(frozen=True, slots=True)
class _StaleReadGuard:
    """Refuses a saved read whose producer the edit removed or moved after it.

    Left alone, the alias would name whichever step now has that position:
    validation reads `step_N` as the Nth step of the edited flow. When the
    template attachment contract runs, the template's placeholder mappings are
    its to judge: it drops the unused ones and refuses a retained one whose
    producer is gone (`template_binding_dependency_broken`).
    """

    existing_order_to_plan_ref: Mapping[int, str]
    positions: Mapping[str, int]
    saved_step_names: Mapping[int, str]
    template_contract_runs: bool
    stale: BoundedListing

    def resolver(self, step: StepSpec, site: str) -> AliasResolver:
        position = self.positions[step.plan_step_ref]

        def resolve(order: int, expression: str) -> str | None:
            plan_ref = self.existing_order_to_plan_ref.get(order)
            if plan_ref is not None and self.positions[plan_ref] < position:
                return plan_ref
            fate = (
                "is removed by this edit" if plan_ref is None else "is moved after it"
            )

            def entry() -> str:
                reader, read, where = map(display_value, (step.name, expression, site))
                producer = display_value(
                    self.saved_step_names.get(order, f"step {order}")
                )
                return (
                    f'Step {position + 1} "{reader}" reads {read} in its {where}; '
                    f'saved step {order} "{producer}" {fate}.'
                )

            self.stale.add(entry)
            return plan_ref

        return resolve

    def raise_if_stale(self) -> None:
        if not self.stale.total:
            return
        raise AIBuilderBadRequestException(
            self.stale.render(
                "This edit removes or moves steps that other kept steps still "
                "read. Change those steps' reads, or keep each producer before "
                "the steps that read it:"
            ),
            code=AIBuilderErrorCode.INVALID_PLAN_STEP_REF,
            context={"stale_read_count": self.stale.total},
        )


def _canonicalize_existing_runtime_aliases(
    step_specs: list[StepSpec],
    *,
    saved_step_names: Mapping[int, str] | None = None,
    template_contract_runs: bool = False,
) -> list[StepSpec]:
    """Rewrite saved aliases to plan refs. Given the saved step names (an edit),
    a read of a removed or moved-after producer is refused, never redirected."""

    existing_order_to_plan_ref = _existing_order_to_plan_ref(step_specs)
    if not existing_order_to_plan_ref:
        return step_specs
    guard = (
        _StaleReadGuard(
            existing_order_to_plan_ref=existing_order_to_plan_ref,
            positions={step.plan_step_ref: i for i, step in enumerate(step_specs)},
            saved_step_names=saved_step_names,
            template_contract_runs=template_contract_runs,
            stale=BoundedListing(),
        )
        if saved_step_names is not None
        else None
    )
    steps = [
        _rewrite_runtime_aliases_for_existing_step(
            step, existing_order_to_plan_ref, guard=guard
        )
        for step in step_specs
    ]
    if guard is not None:
        guard.raise_if_stale()
    return steps


def _rewrite_runtime_aliases_for_existing_step(
    step: StepSpec,
    existing_order_to_plan_ref: dict[int, str],
    *,
    guard: _StaleReadGuard | None = None,
) -> StepSpec:
    if step.existing_step_ref is None:
        return step

    def resolve_at(site: str) -> AliasResolver:
        if guard is None:
            return _resolve_by(existing_order_to_plan_ref)
        return guard.resolver(step, site)

    updates: dict[str, Any] = {}
    rewritten_instructions = rewrite_step_alias_heads(
        step.assistant_spec.instructions,
        resolve_at("instructions"),
    )
    if rewritten_instructions != step.assistant_spec.instructions:
        updates["assistant_spec"] = step.assistant_spec.model_copy(
            update={"instructions": rewritten_instructions}
        )

    if step.input_bindings is not None:
        rewritten_bindings = _rewrite_source_ref_step_aliases(
            {
                key: _rewrite_runtime_alias_value(value, resolve_at(key))
                for key, value in step.input_bindings.items()
            },
            resolve_at(SOURCE_REFS_BINDING_KEY),
        )
        if rewritten_bindings != step.input_bindings:
            updates["input_bindings"] = rewritten_bindings

    if step.output_config is not None:
        # Only the strings the runtime interpolates for the step's mode are
        # reads, found by the owner the platform uses; a metadata key is text.
        # A key normalization deletes reads nothing, and the template's
        # mappings are the attachment contract's when it runs.
        channel = step_output_channel(step)
        unguarded = discarded_output_config_keys(step) | frozenset(
            ["bindings"] if guard is not None and guard.template_contract_runs else []
        )
        by_plan_ref = _resolve_by(existing_order_to_plan_ref)
        at_site = resolve_at("output_config")
        rewritten_output_config = rewrite_config_sites(
            step.output_config,
            channel,
            lambda path, text: rewrite_step_alias_heads(
                text, by_plan_ref if path[0] in unguarded else at_site
            ),
        )
        if rewritten_output_config != step.output_config:
            updates["output_config"] = rewritten_output_config

    return step.model_copy(update=updates) if updates else step


def _rewrite_runtime_alias_value(value: Any, resolve: AliasResolver) -> Any:
    if isinstance(value, str):
        return rewrite_step_alias_heads(value, resolve)
    if isinstance(value, dict):
        return {
            key: _rewrite_runtime_alias_value(inner, resolve)
            for key, inner in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [
            _rewrite_runtime_alias_value(item, resolve)
            for item in cast(list[Any], value)
        ]
    return value


def _rewrite_source_ref_step_aliases(
    input_bindings: Any,
    resolve: AliasResolver,
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
        order = source_ref_step_order(step_ref) if isinstance(step_ref, str) else None
        path = (step_ref, "output", ref.get("output"), ref.get("field_path"))
        plan_ref = (
            resolve(
                order, ".".join(part for part in path if isinstance(part, str) and part)
            )
            if order is not None
            else None
        )
        rewritten_refs.append({**ref, "step_ref": plan_ref} if plan_ref else ref)
    if rewritten_refs == raw_refs:
        return bindings
    return {**bindings, SOURCE_REFS_BINDING_KEY: rewritten_refs}
