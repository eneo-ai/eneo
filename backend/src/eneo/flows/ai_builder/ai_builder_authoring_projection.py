from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_edit_admission import SavedStepTarget
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    FlowInputFieldProvenance,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_input_reference_instruction_hint,
    compile_new_step_draft,
    compile_output_contract,
    compile_review_policy,
    compile_step_input_bindings,
    derive_input_contract,
    derive_output_mode,
    effective_input_type_for_bindings,
    make_plan_step_ref,
    reads_run_text,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    NewStepDraft,
    PreviousFieldRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    elect_main_text_field,
    main_text_beside_fields_detail,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AddStep as IntentAddStep,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AssistantSpecPatch,
    ModifyExistingStep,
    OrderedEditProposal,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    BoundedListing,
    display_value,
)
from eneo.flows.ai_builder.ai_builder_step_reads import (
    ReadSite,
    spec_step_refs,
    step_reads,
)
from eneo.flows.application.flow_draft_materialization import (
    validate_existing_step_ref_coverage,
)
from eneo.flows.enums import FlowInputType, FlowOutputMode
from eneo.flows.flow_authoring_runtime_input import resolve_runtime_input_config
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
    strip_inapplicable_completion_model,
)
from eneo.flows.flow_capability_manifest import supports_step_io_tuple
from eneo.flows.flow_variable_definitions import FlowRunInput
from eneo.flows.input_binding_contract_rules import (
    SOURCE_REFS_BINDING_KEY,
    InputBindingContractError,
    SourceRefBinding,
    question_binding,
    source_ref_bindings,
)
from eneo.flows.template_reference_analyzer import (
    analyze_template,
    referenced_form_fields,
)
from eneo.main.exceptions import BadRequestException


class MaterializedAddStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["add"] = "add"
    step: NewStepDraft


MaterializedOrderedEditStep = Annotated[
    ModifyExistingStep | MaterializedAddStep,
    Field(discriminator="kind"),
]


class MaterializedOrderedEditProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_rationale: str
    assumptions: list[str] = Field(default_factory=list)
    flow_name: str | None = None
    flow_description: str | None = None
    steps: list[MaterializedOrderedEditStep]
    removed_existing_step_refs: frozenset[str] = Field(default_factory=frozenset)
    form_fields: list[FormFieldSpec] | None = None
    form_field_provenance: dict[str, FlowInputFieldProvenance] = Field(
        default_factory=dict
    )


def materialize_ordered_edit_proposal(
    proposal: OrderedEditProposal,
    *,
    primary_runtime_input_type: InputType | None = None,
    primary_runtime_required: bool = True,
) -> MaterializedOrderedEditProposal:
    payload = proposal.model_dump(
        mode="python",
        exclude={"steps", "form_fields"},
        exclude_unset=True,
    )
    if "form_fields" in proposal.model_fields_set:
        payload["form_fields"] = (
            None
            if proposal.form_fields is None
            else [
                FormFieldSpec(
                    name=field.variable_name,
                    label=field.label,
                    type=field.field_type,
                    required=field.required,
                    options=list(field.options) or None,
                )
                for field in proposal.form_fields
            ]
        )
        payload["form_field_provenance"] = {
            field.variable_name: field.provenance
            for field in proposal.form_fields or []
        }
    payload["steps"] = [
        _materialize_ordered_edit_step(
            item,
            step_index=index,
            primary_runtime_input_type=primary_runtime_input_type,
            primary_runtime_required=primary_runtime_required,
        )
        for index, item in enumerate(proposal.steps)
    ]
    return MaterializedOrderedEditProposal.model_validate(payload)


def _materialize_ordered_edit_step(
    item: object,
    *,
    step_index: int,
    primary_runtime_input_type: InputType | None,
    primary_runtime_required: bool,
) -> object:
    if not isinstance(item, IntentAddStep):
        return item
    return MaterializedAddStep(
        step=_new_step_draft_from_semantic_intent(
            item.step,
            step_index=step_index,
            primary_runtime_input_type=primary_runtime_input_type,
            primary_runtime_required=primary_runtime_required,
        )
    )


def _new_step_draft_from_semantic_intent(
    step: SemanticStepIntent,
    *,
    step_index: int,
    primary_runtime_input_type: InputType | None,
    primary_runtime_required: bool,
) -> NewStepDraft:
    if step_index == 0 and primary_runtime_input_type is not None:
        is_primary_runtime_step = True
        input_type = primary_runtime_input_type
    else:
        is_primary_runtime_step = False
        input_type = InputType.TEXT
    return NewStepDraft(
        name=step.name,
        instructions=step.instructions,
        input_type=input_type,
        output_type=step.output_type or OutputType.TEXT,
        runtime_required=primary_runtime_required if is_primary_runtime_step else False,
        knowledge_refs=list(step.knowledge_refs),
        uses_form_fields=list(step.uses_form_fields),
        uses_previous_fields=list(step.uses_previous_fields),
        uses_previous_outputs=list(step.uses_previous_outputs),
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
        output_fields=step.output_fields,
    )


def edit_baseline_spec(
    *, saved: FlowDraftSpecCore, revision: FlowDraftSpecCore | None
) -> FlowDraftSpecCore:
    """The spec an edit starts from, and its run-form fields are the edit's
    baseline fields: those of the revision when a saved step is being revised
    (it may carry an earlier turn's state), else the saved flow's. Preparing the
    proposal, compiling it and judging the final run form all read this one
    spec, so no stage sees a different form than another."""

    return revision if revision is not None else saved


def compile_ordered_edit_proposal(
    *,
    base_spec: FlowDraftSpecCore,
    proposal: MaterializedOrderedEditProposal,
    ui_language: str | None = None,
) -> FlowDraftSpecCore:
    base_by_ref = {
        step.existing_step_ref: step
        for step in base_spec.steps
        if step.existing_step_ref is not None
    }
    form_fields = (
        proposal.form_fields
        if "form_fields" in proposal.model_fields_set
        else base_spec.form_fields
    )
    # `base_spec` is the edit baseline (`edit_baseline_spec`): the saved flow's
    # fields and steps, or the revision's on a saved-step revision.
    saved = _SavedFlow(
        steps=base_spec.steps,
        order_by_name=spec_step_refs(base_spec.steps),
        form_fields=[(field.name, field.type) for field in form_fields or []],
        saved_form_field_names=[field.name for field in base_spec.form_fields or []],
        removed_refs=proposal.removed_existing_step_refs,
    )
    preserved_refs: list[str] = []
    compiled_steps: list[StepSpec] = []

    for index, item in enumerate(proposal.steps):
        plan_ref = make_plan_step_ref(index)
        if isinstance(item, MaterializedAddStep):
            compiled_steps.append(
                compile_new_step_draft(
                    step_draft=item.step,
                    plan_step_ref=plan_ref,
                    prior_steps=compiled_steps,
                    run_input=saved.run_input,
                    ui_language=ui_language,
                    require_declared_previous_fields=True,
                )
            )
            continue

        base_step = base_by_ref.get(item.existing_step_ref)
        if base_step is None:
            preserved_refs.append(item.existing_step_ref)
            continue
        preserved_refs.append(item.existing_step_ref)
        compiled = _compile_existing_step_modification(
            base_step,
            item,
            prior_steps=compiled_steps,
            saved=saved,
            ui_language=ui_language,
        )
        compiled_steps.append(compiled.model_copy(update={"plan_step_ref": plan_ref}))

    validate_existing_step_ref_coverage(
        current_refs=set(base_by_ref),
        preserved_refs=preserved_refs,
        removed_existing_step_refs=proposal.removed_existing_step_refs,
    )

    return FlowDraftSpecCore(
        flow_name=_resolve_flow_name(base_spec, proposal),
        flow_description=_resolve_flow_description(base_spec, proposal),
        steps=compiled_steps,
        form_fields=form_fields,
        document_body_writer_step_refs=_document_body_writer_step_refs(
            base_spec=base_spec,
            compiled_steps=compiled_steps,
        ),
    )


def apply_existing_step_patch(
    existing: StepSpec,
    patch: ModifyExistingStep,
) -> StepSpec:
    updates: dict[str, object] = {}
    fields = patch.model_fields_set

    if "name" in fields:
        if patch.name is None or not patch.name.strip():
            raise AIBuilderBadRequestException(
                f"Step {patch.existing_step_ref}: name cannot be cleared; omit "
                "name to keep the current one.",
                code=AIBuilderErrorCode.BAD_REQUEST,
            )
        updates["name"] = patch.name.strip()
    for field_name in (
        "input_source",
        "input_type",
        "output_type",
    ):
        if field_name in fields:
            updates[field_name] = getattr(patch, field_name)
    if "output_fields" in fields:
        updates["output_contract"] = _edit_output_contract(existing, patch)
    if "review_mode" in fields:
        updates["review_policy"] = compile_review_policy(
            patch.review_mode, existing.review_policy
        )
    if "assistant_spec" in fields:
        if patch.assistant_spec is None:
            raise AIBuilderBadRequestException(
                f"Step {patch.existing_step_ref}: assistant_spec cannot be "
                "cleared; omit it to keep the current one.",
                code=AIBuilderErrorCode.BAD_REQUEST,
            )
        updates["assistant_spec"] = merge_assistant_spec_patch(
            existing.assistant_spec,
            patch.assistant_spec,
        )

    return strip_inapplicable_completion_model(existing.model_copy(update=updates))


def _edit_output_contract(
    existing: StepSpec, patch: ModifyExistingStep
) -> dict[str, object] | None:
    declared = compile_output_contract(patch.output_fields)
    if declared is None:
        return None
    saved = existing.output_contract
    if saved is None:
        return declared
    try:
        fields = _saved_output_fields(saved)
        representable = compile_output_contract(fields)
        # The compact field tree cannot express every saved constraint. Repeating
        # that tree must not erase constraints or turn annotations into edits.
        if representable is not None:
            if _output_schema_shape(declared) == _output_schema_shape(representable):
                return saved
        if representable is None or _output_schema_shape(saved) != _output_schema_shape(
            representable
        ):
            raise _unrepresentable_output_contract(patch)
    except ValidationError as error:
        raise _unrepresentable_output_contract(patch) from error
    return declared


def _unrepresentable_output_contract(
    patch: ModifyExistingStep,
) -> AIBuilderBadRequestException:
    return AIBuilderBadRequestException(
        f"Step {patch.existing_step_ref}: this saved output contract has details "
        "output_fields cannot represent. Omit output_fields only when the request "
        "leaves the contract unchanged; otherwise report that this output-field "
        "change is unsupported. An empty list explicitly removes the contract.",
        code=AIBuilderErrorCode.BAD_REQUEST,
    )


_SCHEMA_OBJECT = TypeAdapter(dict[str, object])
_SCHEMA_STRINGS = TypeAdapter(list[str])


def _schema_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return _SCHEMA_OBJECT.validate_python(value, strict=True)


def _saved_output_fields(
    schema: Mapping[str, object],
) -> list[StructuredFieldDraft] | None:
    properties = _schema_object(schema.get("properties"))
    required = schema.get("required", [])
    if (
        schema.get("type") != "object"
        or properties is None
        or not isinstance(required, list)
    ):
        return None
    required = _SCHEMA_STRINGS.validate_python(required, strict=True)
    fields: list[StructuredFieldDraft] = []
    for name, value in properties.items():
        field = _schema_object(value)
        if field is None:
            return None
        field_type = field.get("type")
        nullable = False
        if isinstance(field_type, list):
            kinds = _SCHEMA_STRINGS.validate_python(field_type, strict=True)
            nullable = "null" in kinds
            non_null = [kind for kind in kinds if kind != "null"]
            if not nullable or len(non_null) != 1:
                return None
            field_type = non_null[0]
        data: dict[str, object] = {
            "name": name,
            "field_type": field_type,
            "description": name,
            "required": name in required,
            "nullable": nullable,
        }
        if field_type == "object":
            children = _saved_output_fields(field)
            if children is None:
                if (
                    "properties" in field
                    or field.get("additionalProperties") is not True
                ):
                    return None
                data["allow_additional_properties"] = True
            else:
                data["fields"] = children
        elif field_type == "array":
            items = _schema_object(field.get("items"))
            if items is None:
                return None
            if items.get("type") == "object":
                children = _saved_output_fields(items)
                if children is None:
                    return None
                data["item_fields"] = children
            elif items.get("type") != "string":
                return None
        draft = StructuredFieldDraft.model_validate(data)
        if draft.name != name:
            return None
        fields.append(draft)
    return fields


def _output_schema_shape(schema: Mapping[str, object]) -> dict[str, object]:
    result = dict(schema)
    result.pop("title", None)
    result.pop("description", None)
    # A complete field replacement uses the compiler's closed object policy;
    # absent/true adds no saved constraint that this replacement would lose.
    if schema.get("type") == "object" and (
        "additionalProperties" not in schema or schema["additionalProperties"] is True
    ):
        result["additionalProperties"] = False
    properties = _schema_object(schema.get("properties"))
    if properties is not None:
        result["properties"] = {
            name: (
                _output_schema_shape(child)
                if (child := _schema_object(value)) is not None
                else value
            )
            for name, value in properties.items()
        }
    items = _schema_object(schema.get("items"))
    if items is not None:
        result["items"] = _output_schema_shape(items)
    for key in ("type", "required"):
        value = schema.get(key)
        if isinstance(value, list):
            strings = _SCHEMA_STRINGS.validate_python(value, strict=True)
            if key == "required" and not strings:
                result.pop(key, None)
            else:
                result[key] = sorted(strings)
    return result


def _compile_existing_step_modification(
    existing: StepSpec,
    patch: ModifyExistingStep,
    *,
    prior_steps: list[StepSpec],
    saved: _SavedFlow,
    ui_language: str | None,
) -> StepSpec:
    fields = patch.authored_fields
    if not fields:
        # A keep entry, or a saved step the fragment left out: nothing is
        # authored, so nothing is derived. The step stays as the base holds it.
        return existing
    step = apply_existing_step_patch(existing, patch)

    # A restated input_source or input_type that equals the saved one, with
    # neither list said, changes nothing: the saved input stays as it is.
    if fields & {"uses_form_fields", "uses_previous_fields"} or (
        step.input_source,
        step.input_type,
    ) != (existing.input_source, existing.input_type):
        _refuse_a_rebuild_that_drops_reads(
            existing, patch, prior_steps=prior_steps, saved=saved
        )
        uses_form_fields = patch.uses_form_fields or []
        uses_previous_fields = patch.uses_previous_fields or []
        input_bindings = compile_step_input_bindings(
            input_source=step.input_source,
            input_type=step.input_type,
            uses_form_fields=uses_form_fields,
            uses_previous_fields=uses_previous_fields,
            uses_previous_outputs=[],
            prior_steps=prior_steps,
            run_input=saved.run_input,
            require_declared_previous_fields=True,
        )
        effective_input_type = effective_input_type_for_bindings(
            input_source=step.input_source,
            input_type=step.input_type,
            input_bindings=input_bindings,
        )
        input_contract = derive_input_contract(
            input_source=step.input_source,
            input_type=effective_input_type,
            prior_steps=prior_steps,
            input_bindings=input_bindings,
        )
        updates: dict[str, object | None] = {
            "input_type": effective_input_type,
            "input_bindings": input_bindings,
            "input_contract": input_contract,
        }
        if input_bindings is None:
            hint = compile_input_reference_instruction_hint(
                uses_previous_fields=uses_previous_fields,
                uses_form_fields=uses_form_fields,
                ui_language=ui_language,
            )
            if hint:
                updates["assistant_spec"] = step.assistant_spec.model_copy(
                    update={
                        "instructions": f"{step.assistant_spec.instructions}\n\n{hint}"
                    }
                )
        step = step.model_copy(update=updates)
        input_config = resolve_runtime_input_config(step_spec=step)
        if input_config != step.input_config:
            step = step.model_copy(update={"input_config": input_config})

    # The persisted mode is the author's choice; derive_output_mode cannot
    # even produce compose_text or speaker_mapping. It is rederived only when
    # the patch names the delivery mode, the one field that asks for a mode,
    # or when the patched types make the persisted mode illegal by engine
    # truth (the audio repair rewires a transcribe_only step to text input;
    # a text step turned PDF cannot stay pass_through). A same-IO change,
    # such as new bindings on a text composer, keeps the mode.
    if "document_delivery_mode" in fields or not supports_step_io_tuple(
        input_type=FlowInputType(step.input_type.value),
        output_type=step.output_type,
        output_mode=FlowOutputMode(step.output_mode.value),
    ):
        output_mode = _derive_existing_step_output_mode(
            step,
            document_delivery_mode=patch.document_delivery_mode,
        )
        if output_mode != step.output_mode:
            step = step.model_copy(update={"output_mode": output_mode})

    return strip_inapplicable_completion_model(step)


_KEEP_AS_SAVED = "leave input_source, input_type and both lists null"


@dataclass(frozen=True, slots=True)
class _SavedFlow:
    """The saved flow a modify is judged against, and what the edit drops."""

    steps: Sequence[StepSpec]
    order_by_name: Mapping[str, int]
    # The edited flow's declared run-form fields as (name, type); a type is None
    # where only the names are known.
    form_fields: Sequence[tuple[str, str | None]]
    saved_form_field_names: Sequence[str]
    removed_refs: frozenset[str]

    @property
    def form_field_names(self) -> list[str]:
        return [name for name, _ in self.form_fields]

    @property
    def run_input(self) -> FlowRunInput:
        """What the edited flow's run form collects."""

        return FlowRunInput(form_fields=bool(self.form_field_names))

    def by_order(self, bindings: dict[str, Any] | None) -> dict[str, Any] | None:
        """Well-formed bindings with each source ref's step named by its saved
        order, so a compiled ref and a saved alias of one step compare equal."""

        refs: list[Any] = (bindings or {}).get(SOURCE_REFS_BINDING_KEY) or []
        return bindings and {
            **bindings,
            SOURCE_REFS_BINDING_KEY: [
                {**ref, "step_ref": self.order_by_name.get(ref["step_ref"])}
                for ref in refs
            ],
        }


def _restated_lists(
    step: StepSpec, saved: _SavedFlow, own_order: int
) -> tuple[list[str], list[PreviousFieldRef]] | None:
    """The lists that compile back to the step's saved input exactly, or None:
    anything else in it (literal text, a runtime, indexed, whole or templated
    read) a rebuild would lose, so the compiler is the judge."""

    try:
        forms = question_form_reads(step.input_bindings, saved.saved_form_field_names)
        fields = [
            PreviousFieldRef(
                from_step=saved.order_by_name[ref.step_ref],
                field_path=".".join(ref.field_path),
                label=ref.label,
            )
            for ref in source_ref_bindings(step.input_bindings)
            if ref.field_path and ref.step_ref in saved.order_by_name
        ]
        # The saved flow's run form, then the free-text run: a form flow saved
        # while the compiler still wrote the run text into its first step's
        # input restates as that, so a rebuild can drop the read the run
        # never supplies.
        for run_input in (
            FlowRunInput(form_fields=bool(saved.saved_form_field_names)),
            FlowRunInput(),
        ):
            compiled = compile_step_input_bindings(
                input_source=step.input_source,
                input_type=step.input_type,
                uses_form_fields=forms,
                uses_previous_fields=fields,
                uses_previous_outputs=[],
                prior_steps=list(saved.steps[: own_order - 1]),
                run_input=run_input,
                require_declared_previous_fields=True,
            )
            if saved.by_order(compiled) == saved.by_order(step.input_bindings):
                return forms, fields
    except (
        AIBuilderArchitectureError,
        BadRequestException,
        InputBindingContractError,
        ValidationError,
    ):
        return None
    return None


def _refuse_a_rebuild_that_drops_reads(
    existing: StepSpec,
    patch: ModifyExistingStep,
    *,
    prior_steps: list[StepSpec],
    saved: _SavedFlow,
) -> None:
    """Refuse a rebuild of the step's input (compiled from the lists, a null
    list as empty) that would drop a saved read nobody named, offering only a
    repair that can pass. A read of a removed step is replaced only by reads
    the model names, and an inexact input can only be kept as saved."""

    own_order = saved.order_by_name.get(existing.existing_step_ref or "")
    if existing.input_bindings is None or own_order is None:
        return
    if reads_run_text(existing) and not saved.run_input.free_text:
        declared = list(saved.form_fields)
        elected = elect_main_text_field(declared)
        if elected is None or elected not in set(patch.uses_form_fields or []):
            raise AIBuilderBadRequestException(
                f'Step {own_order} "{display_value(existing.name)}" '
                f"({existing.existing_step_ref}) reads the flow's main text, and a "
                "rebuild would drop that read. "
                + main_text_beside_fields_detail(
                    can_declare_fields=True, fields=declared
                ),
                code=AIBuilderErrorCode.INVALID_PLAN_STEP_REF,
            )
    position = len(prior_steps) + 1
    before = {
        step.existing_step_ref: order
        for order, step in enumerate(prior_steps, 1)
        if step.existing_step_ref is not None
    }
    shown = BoundedListing()
    lists = _restated_lists(existing, saved, own_order)
    # Removed or moved-after producers come first, one entry each, since
    # every repair must name them: the step name, how often, and one read.
    gone: dict[str, tuple[StepSpec, int, str]] = {}
    for read in step_reads(
        existing,
        order=own_order,
        step_refs=dict(saved.order_by_name),
        form_field_names=set(saved.form_field_names),
    ):
        order = read.producer_order
        producer = saved.steps[order - 1] if order and order <= own_order else None
        if read.site not in (ReadSite.SOURCE_REF, ReadSite.QUESTION) or (
            producer is None or producer.existing_step_ref in before
        ):
            continue
        origin = read.origin
        expression = (
            origin.template_expression()
            if isinstance(origin, SourceRefBinding)
            else str(origin)
        )
        _, count, first = gone.get(
            producer.existing_step_ref or "", (producer, 0, expression)
        )
        gone[producer.existing_step_ref or ""] = (producer, count + 1, first)
    for producer, count, expression in gone.values():
        fate = (
            "is removed by this edit"
            if producer.existing_step_ref in saved.removed_refs
            else "is moved after it"
        )
        shown.add(
            lambda producer=producer, fate=fate, count=count, expression=expression: (
                f'saved step "{display_value(producer.name)}" {fate}; read {count} '
                f"time{'' if count == 1 else 's'}, e.g. {display_value(expression)}"
            )
        )
    # Then the step's reads as the model restates them, one per entry,
    # formatted only when shown; field reads in this edit's step order.
    for form in lists[0] if lists else ():
        if form in saved.form_field_names:
            shown.add(
                lambda form=form: f"uses_form_fields: {json.dumps(display_value(form), ensure_ascii=False)}"
            )
    for ref in lists[1] if lists else ():
        producer_ref = saved.steps[ref.from_step - 1].existing_step_ref
        if producer_ref is not None and producer_ref in before:
            field_read = {
                "producer": SavedStepTarget(
                    existing_step_ref=producer_ref
                ).model_dump(),
                "field_path": display_value(ref.field_path),
                "label": display_value(ref.label or ""),
            }
            shown.add(
                lambda field_read=field_read: (
                    "uses_previous_fields: "
                    f"{json.dumps(field_read, ensure_ascii=False)}"
                )
            )
    step = f'Step {position} "{display_value(existing.name)}"'
    unsaid = [
        name
        for name, reads in zip(
            ("uses_form_fields", "uses_previous_fields"), lists or ()
        )
        if reads and name not in patch.authored_fields
    ]
    # Leaving the input null keeps every saved read, so each step read that the
    # edit removes or moves must stay before it too. Stated in full, by count,
    # so the repair never depends on names the listing may cut.
    keep = (
        f"keep every step it reads before it ({len(gone)} of them this edit "
        f"removes or moves after it) and {_KEEP_AS_SAVED}"
        if gone
        else _KEEP_AS_SAVED
    )
    if lists is None:
        heading = (
            f"{step} has an input the edit tool cannot restate exactly, so a new "
            f"input would drop part of it. To keep it, {keep}."
        )
    elif gone and not (patch.uses_form_fields or patch.uses_previous_fields):
        heading = (
            f"{step} reads steps this edit removes or moves after it. Name what "
            f"step {position} reads instead in uses_form_fields and "
            f"uses_previous_fields, or {keep}."
        )
    elif unsaid:
        heading = (
            f"{step} changes its input, but {' and '.join(unsaid)} "
            f"{'is' if len(unsaid) == 1 else 'are'} null, so its current reads "
            f"would be dropped. To keep them, give both lists complete, or {keep}."
        )
    else:
        return
    raise AIBuilderBadRequestException(
        shown.render(heading + (" Its reads:" if shown.total else "")),
        code=AIBuilderErrorCode.INVALID_PLAN_STEP_REF,
        context={"refused_read_count": shown.total},
    )


def input_restates_exactly(
    step: StepSpec,
    *,
    prior_steps: Sequence[StepSpec],
    form_field_names: Sequence[str],
) -> bool:
    """Whether a saved step's input compiles back exactly from its lists."""

    steps = [*prior_steps, step]
    saved = _SavedFlow(
        steps=steps,
        order_by_name=spec_step_refs(steps),
        form_fields=[(name, None) for name in form_field_names],
        saved_form_field_names=form_field_names,
        removed_refs=frozenset(),
    )
    return (
        step.input_bindings is None
        or _restated_lists(step, saved, len(steps)) is not None
    )


def question_form_reads(
    input_bindings: object, form_field_names: Sequence[str]
) -> list[str]:
    """The form fields a saved question reads, in the order it reads them."""

    question = question_binding(input_bindings)
    if question is None:
        return []
    references = analyze_template(
        question, step_refs={}, form_field_names=set(form_field_names)
    )
    return list(
        dict.fromkeys(
            name
            for reference in references
            for name in sorted(referenced_form_fields([reference]))
        )
    )


def _derive_existing_step_output_mode(
    step: StepSpec,
    *,
    document_delivery_mode: DocumentDeliveryMode | None,
) -> OutputMode:
    return derive_output_mode(
        input_type=step.input_type,
        output_type=step.output_type,
        document_delivery_mode=(
            document_delivery_mode
            if document_delivery_mode is not None
            else _document_delivery_mode_for_existing_step(step)
        ),
    )


def _document_delivery_mode_for_existing_step(
    step: StepSpec,
) -> DocumentDeliveryMode:
    if (
        step.output_mode == OutputMode.TEMPLATE_FILL
        and step.output_type == OutputType.DOCX
    ):
        return "template_fill"
    if step.output_type in {OutputType.DOCX, OutputType.PDF}:
        return "generated"
    return "not_applicable"


def merge_assistant_spec_patch(
    existing: AssistantSpec,
    patch: AssistantSpecPatch,
) -> AssistantSpec:
    patched_fields = patch.model_fields_set

    instructions = existing.instructions
    if "instructions" in patched_fields:
        if patch.instructions is None or not patch.instructions.strip():
            raise AIBuilderBadRequestException(
                "assistant_spec.instructions cannot be cleared; omit it to keep "
                "the current instructions.",
                code=AIBuilderErrorCode.BAD_REQUEST,
            )
        instructions = patch.instructions.strip()

    knowledge_refs = existing.knowledge_refs
    if "knowledge_refs" in patched_fields:
        knowledge_refs = patch.knowledge_refs

    return AssistantSpec(
        instructions=instructions,
        model_ref=existing.model_ref,
        knowledge_refs=knowledge_refs,
    )


def _document_body_writer_step_refs(
    *,
    base_spec: FlowDraftSpecCore,
    compiled_steps: list[StepSpec],
) -> tuple[str, ...] | None:
    base_refs = base_spec.document_body_writer_step_refs
    if base_refs is None:
        return None

    base_step_by_plan_ref = {step.plan_step_ref: step for step in base_spec.steps}
    next_ref_by_existing_ref = {
        step.existing_step_ref: step.plan_step_ref
        for step in compiled_steps
        if step.existing_step_ref is not None
    }
    refs: list[str] = []
    for base_ref in base_refs:
        base_step = base_step_by_plan_ref.get(base_ref)
        if base_step is None or base_step.existing_step_ref is None:
            continue
        next_ref = next_ref_by_existing_ref.get(base_step.existing_step_ref)
        if next_ref is not None:
            refs.append(next_ref)
    return tuple(refs) or None


def _resolve_flow_name(
    base_spec: FlowDraftSpecCore,
    proposal: MaterializedOrderedEditProposal,
) -> str:
    # The edit tool promises "null to keep current"; a blank name has no other
    # honest reading either. Raising here after the provider answered turned
    # a whole turn into "connection lost" for the user.
    if "flow_name" not in proposal.model_fields_set:
        return base_spec.flow_name
    if proposal.flow_name is None or not proposal.flow_name.strip():
        return base_spec.flow_name
    return proposal.flow_name.strip()


def _resolve_flow_description(
    base_spec: FlowDraftSpecCore,
    proposal: MaterializedOrderedEditProposal,
) -> str:
    if "flow_description" not in proposal.model_fields_set:
        return base_spec.flow_description
    # Null keeps the current description, as the tool schema says; an empty
    # string is an explicit clearing.
    if proposal.flow_description is None:
        return base_spec.flow_description
    return proposal.flow_description.strip()


__all__ = [
    "MaterializedAddStep",
    "MaterializedOrderedEditProposal",
    "MaterializedOrderedEditStep",
    "compile_ordered_edit_proposal",
    "materialize_ordered_edit_proposal",
    "merge_assistant_spec_patch",
]
