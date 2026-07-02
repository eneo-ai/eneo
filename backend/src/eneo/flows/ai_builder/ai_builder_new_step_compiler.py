from __future__ import annotations

import logging
import string
from typing import Any

from eneo.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    NewStepDraft,
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
from eneo.flows.flow_authoring_runtime_input import resolve_runtime_input_config
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
    completion_model_ref_strip_log_extra,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.flow_variable_definitions import form_field_reference_expression

logger = logging.getLogger(__name__)
_FILE_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}


def derive_position_input_source(step_index: int) -> InputSource:
    return InputSource.FLOW_INPUT if step_index == 0 else InputSource.PREVIOUS_STEP


def resolve_omitted_input_source(
    step_draft: NewStepDraft,
    *,
    step_index: int,
) -> NewStepDraft:
    if step_draft.input_source is not None:
        return step_draft
    return step_draft.model_copy(
        update={"input_source": derive_position_input_source(step_index)}
    )


def normalize_new_step_input_shape(
    step_draft: NewStepDraft,
    *,
    step_index: int,
) -> NewStepDraft:
    step_draft = resolve_omitted_input_source(step_draft, step_index=step_index)
    input_source = require_resolved_input_source(step_draft)
    input_type = step_draft.input_type

    if input_source == InputSource.ALL_PREVIOUS_STEPS and input_type == InputType.JSON:
        input_type = InputType.TEXT
    if (
        input_source != InputSource.FLOW_INPUT
        and step_draft.output_type == OutputType.TEXT
        and input_type == InputType.JSON
        and (step_draft.uses_previous_fields or step_draft.uses_previous_outputs)
    ):
        input_type = InputType.TEXT
    if input_source != InputSource.FLOW_INPUT and input_type in _FILE_INPUT_TYPES:
        input_type = InputType.TEXT

    if input_type == step_draft.input_type:
        return step_draft
    return step_draft.model_copy(update={"input_type": input_type})


def compile_new_step_draft(
    *,
    step_draft: NewStepDraft,
    plan_step_ref: str,
    prior_steps: list[StepSpec],
) -> StepSpec:
    step_draft = normalize_new_step_input_shape(
        step_draft,
        step_index=len(prior_steps),
    )
    input_source = require_resolved_input_source(step_draft)
    output_mode = derive_new_step_output_mode(step_draft)
    output_contract = compile_output_contract(step_draft.output_fields)
    input_config = compile_runtime_input_overrides(step_draft)
    input_bindings = compile_input_bindings(step_draft, prior_steps)
    input_contract = derive_input_contract(
        input_source=input_source,
        input_type=step_draft.input_type,
        prior_steps=prior_steps,
        input_bindings=input_bindings,
    )
    assistant_instructions = compile_assistant_instructions(
        step_draft=step_draft,
        input_bindings=input_bindings,
    )
    output_config = compile_output_config(step_draft)

    step = StepSpec(
        plan_step_ref=plan_step_ref,
        name=step_draft.name,
        assistant_spec=AssistantSpec(
            instructions=assistant_instructions,
            model_ref=step_draft.model_ref,
            knowledge_refs=list(step_draft.knowledge_refs),
            mcp_server_refs=list(step_draft.mcp_server_refs),
            mcp_tool_refs=list(step_draft.mcp_tool_refs),
        ),
        mcp_policy=MCPPolicy.INHERIT,
        input_source=input_source,
        input_type=step_draft.input_type,
        output_mode=output_mode,
        output_type=step_draft.output_type,
        input_bindings=input_bindings,
        input_contract=input_contract,
        output_contract=output_contract,
        input_config=input_config,
        output_config=output_config,
        review_policy=compile_review_policy(step_draft.review_mode),
    )
    step = step.model_copy(
        update={"input_config": resolve_runtime_input_config(step_spec=step)}
    )
    _log_transcribe_only_model_ref_stripped(
        supplied_model_ref=step_draft.model_ref,
        validated_step=step,
        source="draft",
    )
    return step


def require_resolved_input_source(step_draft: NewStepDraft) -> InputSource:
    if step_draft.input_source is None:
        raise ValueError("New step input_source must be resolved before compilation.")
    return step_draft.input_source


def _log_transcribe_only_model_ref_stripped(
    *,
    supplied_model_ref: str | None,
    validated_step: StepSpec,
    source: str,
) -> None:
    extra = completion_model_ref_strip_log_extra(
        supplied_model_ref=supplied_model_ref,
        validated_step=validated_step,
        source=source,
    )
    if extra is None:
        return
    logger.info("ai_builder_transcribe_only_model_ref_stripped", extra=extra)


def make_plan_step_ref(index: int) -> str:
    if index < len(string.ascii_lowercase):
        return f"step_{string.ascii_lowercase[index]}"
    return f"step_{index + 1}"


def derive_output_mode(
    *,
    input_type: InputType,
    output_type: OutputType,
    document_delivery_mode: DocumentDeliveryMode,
) -> OutputMode:
    if input_type == InputType.AUDIO and output_type == OutputType.TEXT:
        return OutputMode.TRANSCRIBE_ONLY
    if output_type == OutputType.DOCX and document_delivery_mode == "template_fill":
        return OutputMode.TEMPLATE_FILL
    return OutputMode.PASS_THROUGH


def derive_new_step_output_mode(step_draft: NewStepDraft) -> OutputMode:
    return derive_output_mode(
        input_type=step_draft.input_type,
        output_type=step_draft.output_type,
        document_delivery_mode=step_draft.document_delivery_mode,
    )


def compile_runtime_input_overrides(step_draft: NewStepDraft) -> dict[str, Any] | None:
    if not step_draft.runtime_required and step_draft.runtime_max_files is None:
        return None

    runtime_input: dict[str, Any] = {"required": step_draft.runtime_required}
    if step_draft.runtime_max_files is not None:
        runtime_input["max_files"] = step_draft.runtime_max_files
    return {"runtime_input": runtime_input}


def compile_output_config(step_draft: NewStepDraft) -> dict[str, Any] | None:
    if step_draft.citations_requested:
        return {"citation_mode": "inline_inref_sidecar"}
    return None


def compile_review_policy(
    review_mode: FlowStepReviewMode | None,
) -> FlowStepReviewPolicy | None:
    if review_mode is None:
        return None
    return FlowStepReviewPolicy(mode=review_mode)


def compile_input_bindings(
    step_draft: NewStepDraft,
    prior_steps: list[StepSpec],
) -> dict[str, Any] | None:
    """Compile explicit "Underlag till text" only when implicit input is insufficient.

    Runtime treats `input_bindings.question` as the complete effective input for
    the step. It replaces, rather than augments, `input_source`. For that reason
    the compiler should leave bindings empty for normal chains and broad fan-in
    steps unless it must compose material from multiple sources.
    """
    input_source = require_resolved_input_source(step_draft)
    return compile_step_input_bindings(
        input_source=input_source,
        input_type=step_draft.input_type,
        uses_form_fields=step_draft.uses_form_fields,
        uses_previous_fields=step_draft.uses_previous_fields,
        uses_previous_outputs=step_draft.uses_previous_outputs,
        prior_steps=prior_steps,
    )


def compile_step_input_bindings(
    *,
    input_source: InputSource,
    input_type: InputType,
    uses_form_fields: list[str],
    uses_previous_fields: list[PreviousFieldRef],
    uses_previous_outputs: list[PreviousOutputRef],
    prior_steps: list[StepSpec],
) -> dict[str, Any] | None:
    """Compile explicit "Underlag till text" for a step in plan-ref order."""
    if input_source.value == "all_previous_steps":
        return None

    source_reference = _resolve_source_reference(
        input_source=input_source,
        input_type=input_type,
        prior_steps=prior_steps,
    )
    explicit_previous_fields = _compile_previous_field_sections(
        uses_previous_fields,
        prior_steps,
    )
    explicit_previous_outputs = _compile_previous_output_sections(
        uses_previous_outputs,
        prior_steps,
    )
    structured_previous_text_input = (
        input_source.value == "previous_step"
        and input_type.value == "text"
        and bool(prior_steps)
        and prior_steps[-1].output_type == OutputType.JSON
    )
    needs_explicit_underlag = bool(
        explicit_previous_fields
        or explicit_previous_outputs
        or uses_form_fields
        or structured_previous_text_input
    )

    if input_source.value == "previous_step" and not needs_explicit_underlag:
        return None

    if (
        source_reference is None
        and not explicit_previous_fields
        and not explicit_previous_outputs
        and not uses_form_fields
    ):
        return None

    explicit_previous_sections = [*explicit_previous_fields, *explicit_previous_outputs]
    sections: list[str] = []
    if source_reference is not None and not _should_suppress_source_reference(
        input_source=input_source,
        uses_previous_fields=uses_previous_fields,
        prior_steps=prior_steps,
        source_reference=source_reference,
        explicit_previous_sections=explicit_previous_sections,
    ):
        sections.append(source_reference)
    sections.extend(explicit_previous_fields)
    sections.extend(explicit_previous_outputs)
    if uses_form_fields:
        form_field_lines = [
            f"{field_name}: {form_field_reference_expression(field_name)}"
            for field_name in uses_form_fields
        ]
        sections.append("\n".join(form_field_lines))
    if not sections:
        return None
    return {"question": "\n\n".join(sections)}


def _should_suppress_source_reference(
    *,
    input_source: InputSource,
    uses_previous_fields: list[PreviousFieldRef],
    prior_steps: list[StepSpec],
    source_reference: str,
    explicit_previous_sections: list[str],
) -> bool:
    if not explicit_previous_sections:
        return False
    if not _is_immediate_structured_source_reference(
        input_source=input_source,
        prior_steps=prior_steps,
        source_reference=source_reference,
    ):
        return False
    immediate_previous_order = len(prior_steps)
    # A targeted field ref to the immediate JSON predecessor is enough to drop
    # the broad structured source blob.
    return any(
        field_ref.from_step == immediate_previous_order
        for field_ref in uses_previous_fields
    )


def _is_immediate_structured_source_reference(
    *,
    input_source: InputSource,
    prior_steps: list[StepSpec],
    source_reference: str,
) -> bool:
    if input_source.value != "previous_step":
        return False
    if not prior_steps:
        return False
    previous_step = prior_steps[-1]
    if previous_step.output_type != OutputType.JSON:
        return False
    return (
        source_reference == f"{{{{ {previous_step.plan_step_ref}.output.structured }}}}"
    )


def compile_assistant_instructions(
    *,
    step_draft: NewStepDraft,
    input_bindings: dict[str, Any] | None,
) -> str:
    instructions = step_draft.instructions
    if input_bindings is None:
        hint = compile_input_reference_instruction_hint(
            uses_previous_fields=step_draft.uses_previous_fields,
            uses_form_fields=step_draft.uses_form_fields,
        )
        if hint:
            instructions = f"{instructions}\n\n{hint}"

    return _append_output_field_guidance(
        instructions=instructions or "",
        output_fields=step_draft.output_fields,
    )


def compile_input_reference_instruction_hint(
    *,
    uses_previous_fields: list[PreviousFieldRef],
    uses_form_fields: list[str],
) -> str:
    sections: list[str] = []
    if uses_previous_fields:
        field_lines = "\n".join(
            f"- {field_ref.label or default_previous_field_label(field_ref.field_path)} "
            f"(steg {field_ref.from_step}: {field_ref.field_path})"
            for field_ref in uses_previous_fields
        )
        sections.append(
            f"Beakta särskilt följande strukturerade fält i underlaget:\n{field_lines}"
        )
    if uses_form_fields:
        form_lines = "\n".join(
            f"- {field_name}: {form_field_reference_expression(field_name)}"
            for field_name in uses_form_fields
        )
        sections.append(
            f"Beakta också följande formulärfält vid analysen:\n{form_lines}"
        )
    return "\n\n".join(sections)


def compile_output_contract(
    output_fields: list[StructuredFieldDraft] | None,
) -> dict[str, Any] | None:
    if not output_fields:
        return None
    return _compile_object_schema(output_fields)


def derive_input_contract(
    *,
    input_source: InputSource,
    input_type: InputType,
    prior_steps: list[StepSpec],
    input_bindings: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if input_type != InputType.JSON:
        return None
    if input_bindings is not None:
        # Explicit underlag replaces the implicit previous-step JSON input, so a
        # contract copied from the previous step would validate the wrong shape.
        return None
    if input_source != InputSource.PREVIOUS_STEP or not prior_steps:
        return None
    return prior_steps[-1].output_contract


def _resolve_source_reference(
    *,
    input_source: InputSource,
    input_type: InputType,
    prior_steps: list[StepSpec],
) -> str | None:
    input_source_value = input_source.value
    input_type_value = input_type.value

    if input_source_value == "flow_input":
        if input_type_value == "json":
            return "{{ indata_json }}"
        if input_type_value in {"document", "file", "audio"}:
            return "{{ step_input.text }}"
        return "{{ indata_text }}"

    if input_source_value == "previous_step":
        if not prior_steps:
            return None
        previous_step = prior_steps[-1]
        if input_type_value == "json":
            return f"{{{{ {previous_step.plan_step_ref}.output.structured }}}}"
        if previous_step.output_type == OutputType.JSON:
            return f"{{{{ {previous_step.plan_step_ref}.output.structured }}}}"
        return f"{{{{ {previous_step.plan_step_ref}.output.text }}}}"

    if input_source_value == "all_previous_steps":
        references = [
            f"{{{{ {step.plan_step_ref}.output.text }}}}" for step in prior_steps
        ]
        return "\n\n".join(references) if references else None

    return None


def _compile_previous_field_sections(
    uses_previous_fields: list[PreviousFieldRef],
    prior_steps: list[StepSpec],
) -> list[str]:
    sections: list[str] = []
    for field_ref in uses_previous_fields:
        if field_ref.from_step < 1 or field_ref.from_step > len(prior_steps):
            continue
        source_step = prior_steps[field_ref.from_step - 1]
        label = field_ref.label or default_previous_field_label(field_ref.field_path)
        sections.append(
            f"{label}: {{{{ {source_step.plan_step_ref}.output.structured.{field_ref.field_path} }}}}"
        )
    return sections


def _compile_previous_output_sections(
    uses_previous_outputs: list[PreviousOutputRef],
    prior_steps: list[StepSpec],
) -> list[str]:
    sections: list[str] = []
    for output_ref in uses_previous_outputs:
        if output_ref.from_step < 1 or output_ref.from_step > len(prior_steps):
            continue
        source_step = prior_steps[output_ref.from_step - 1]
        label = output_ref.label or f"Step {output_ref.from_step} output"
        sections.append(f"{label}: {{{{ {source_step.plan_step_ref}.output.text }}}}")
    return sections


def default_previous_field_label(field_path: str) -> str:
    tokens = [token for token in field_path.split(".") if token and not token.isdigit()]
    if not tokens:
        return field_path
    return tokens[-1].replace("_", " ")


def _compile_object_schema(fields: list[StructuredFieldDraft]) -> dict[str, Any]:
    properties = {field.name: _compile_field_schema(field) for field in fields}
    required = [field.name for field in fields if field.required]
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _compile_field_schema(field: StructuredFieldDraft) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": field.field_type,
        "title": field.name.replace("_", " ").capitalize(),
        "description": field.description,
    }
    if field.field_type == "object" and field.fields is not None:
        schema.update(_compile_object_schema(field.fields))
    elif field.field_type == "array":
        schema["items"] = _compile_array_items_schema(field)
    return schema


def _compile_array_items_schema(field: StructuredFieldDraft) -> dict[str, Any]:
    if field.item_fields:
        return _compile_object_schema(field.item_fields)
    return {"type": "string"}


def _append_output_field_guidance(
    *,
    instructions: str,
    output_fields: list[StructuredFieldDraft] | None,
) -> str:
    if not output_fields:
        return instructions

    normalized_instructions = instructions.casefold()
    guidance_lines: list[str] = []
    top_level_fields = [
        field
        for field in output_fields
        if field.name and field.name.casefold() not in normalized_instructions
    ]
    guidance_lines.extend(
        f"- {field.name}: {field.description}" for field in top_level_fields
    )
    guidance_lines.extend(_nested_output_field_guidance(output_fields))
    if not guidance_lines:
        return instructions

    return f"{instructions}\n\nRequired JSON fields:\n{chr(10).join(guidance_lines)}"


def _nested_output_field_guidance(
    output_fields: list[StructuredFieldDraft],
    *,
    parent_path: str = "",
) -> list[str]:
    lines: list[str] = []
    for field in output_fields:
        if not field.name:
            continue
        field_path = f"{parent_path}.{field.name}" if parent_path else field.name
        if field.field_type == "array" and field.item_fields:
            item_names = _field_name_list(field.item_fields)
            if item_names:
                lines.append(
                    f"Allowed fields for items of {field_path}: {item_names}. "
                    "Do not emit other fields."
                )
            lines.extend(
                _nested_output_field_guidance(
                    field.item_fields,
                    parent_path=f"{field_path}[]",
                )
            )
        elif field.field_type == "object" and field.fields:
            object_names = _field_name_list(field.fields)
            if object_names:
                lines.append(
                    f"Allowed fields for object {field_path}: {object_names}. "
                    "Do not emit other fields."
                )
            lines.extend(
                _nested_output_field_guidance(
                    field.fields,
                    parent_path=field_path,
                )
            )
    return lines


def _field_name_list(fields: list[StructuredFieldDraft]) -> str:
    return ", ".join(field.name for field in fields if field.name)
