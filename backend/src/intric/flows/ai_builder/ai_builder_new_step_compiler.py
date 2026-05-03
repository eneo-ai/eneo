from __future__ import annotations

import string
from typing import Any

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)


def compile_new_step_draft(
    *,
    step_draft: NewStepDraft,
    step_index: int,
    prior_steps: list[StepSpec],
) -> StepSpec:
    plan_step_ref = make_plan_step_ref(step_index)
    output_mode = derive_new_step_output_mode(step_draft)
    output_contract = compile_output_contract(step_draft.output_fields)
    input_contract = _derive_input_contract(step_draft, prior_steps)
    input_config = compile_input_config(step_draft)
    input_bindings = compile_input_bindings(step_draft, prior_steps)
    assistant_instructions = compile_assistant_instructions(
        step_draft=step_draft,
        input_bindings=input_bindings,
    )
    output_config = compile_output_config(step_draft)

    return StepSpec(
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
        input_source=step_draft.input_source,
        input_type=step_draft.input_type,
        output_mode=output_mode,
        output_type=step_draft.output_type,
        input_bindings=input_bindings,
        input_contract=input_contract,
        output_contract=output_contract,
        input_config=input_config,
        output_config=output_config,
    )


def make_plan_step_ref(index: int) -> str:
    if index < len(string.ascii_lowercase):
        return f"step_{string.ascii_lowercase[index]}"
    return f"step_{index + 1}"


def derive_new_step_output_mode(step_draft: NewStepDraft) -> OutputMode:
    if (
        step_draft.input_type.value == "audio"
        and step_draft.output_type.value == "text"
    ):
        return OutputMode.TRANSCRIBE_ONLY
    if (
        step_draft.output_type == OutputType.DOCX
        and step_draft.document_delivery_mode == "template_fill"
    ):
        return OutputMode.TEMPLATE_FILL
    return OutputMode.PASS_THROUGH


def compile_input_config(step_draft: NewStepDraft) -> dict[str, Any] | None:
    if not step_draft.runtime_upload:
        return None

    runtime_input: dict[str, Any] = {
        "enabled": True,
        "required": step_draft.runtime_required,
        "input_format": step_draft.input_type.value,
    }
    if step_draft.runtime_max_files is not None:
        runtime_input["max_files"] = step_draft.runtime_max_files
    return {"runtime_input": runtime_input}


def compile_output_config(step_draft: NewStepDraft) -> dict[str, Any] | None:
    if step_draft.citations_requested:
        return {"citation_mode": "inline_inref_sidecar"}
    return None


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
    if step_draft.input_source.value == "all_previous_steps":
        return None

    source_reference = _resolve_source_reference(step_draft, prior_steps)
    explicit_previous_fields = _compile_previous_field_sections(step_draft, prior_steps)
    explicit_previous_outputs = _compile_previous_output_sections(
        step_draft,
        prior_steps,
    )
    structured_previous_text_input = (
        step_draft.input_source.value == "previous_step"
        and step_draft.input_type.value == "text"
        and bool(prior_steps)
        and prior_steps[-1].output_type == OutputType.JSON
    )
    needs_explicit_underlag = bool(
        explicit_previous_fields
        or explicit_previous_outputs
        or step_draft.uses_form_fields
        or structured_previous_text_input
    )

    if step_draft.input_source.value == "previous_step" and not needs_explicit_underlag:
        return None

    if (
        source_reference is None
        and not explicit_previous_fields
        and not explicit_previous_outputs
    ):
        return None

    explicit_previous_sections = [*explicit_previous_fields, *explicit_previous_outputs]
    sections: list[str] = []
    if source_reference is not None and not _should_suppress_source_reference(
        step_draft=step_draft,
        prior_steps=prior_steps,
        source_reference=source_reference,
        explicit_previous_sections=explicit_previous_sections,
    ):
        sections.append(source_reference)
    sections.extend(explicit_previous_fields)
    sections.extend(explicit_previous_outputs)
    if step_draft.uses_form_fields:
        form_field_lines = [
            f"{field_name}: {{{{ {field_name} }}}}"
            for field_name in step_draft.uses_form_fields
        ]
        sections.append("\n".join(form_field_lines))
    if not sections:
        return None
    return {"question": "\n\n".join(sections)}


def _should_suppress_source_reference(
    *,
    step_draft: NewStepDraft,
    prior_steps: list[StepSpec],
    source_reference: str,
    explicit_previous_sections: list[str],
) -> bool:
    if not explicit_previous_sections:
        return False
    if not _is_immediate_structured_source_reference(
        step_draft=step_draft,
        prior_steps=prior_steps,
        source_reference=source_reference,
    ):
        return False
    immediate_previous_order = len(prior_steps)
    refs = [
        *(field_ref.from_step for field_ref in step_draft.uses_previous_fields),
        *(output_ref.from_step for output_ref in step_draft.uses_previous_outputs),
    ]
    return bool(refs) and all(
        from_step == immediate_previous_order for from_step in refs
    )


def _is_immediate_structured_source_reference(
    *,
    step_draft: NewStepDraft,
    prior_steps: list[StepSpec],
    source_reference: str,
) -> bool:
    if step_draft.input_source.value != "previous_step":
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
    if input_bindings is None and step_draft.uses_previous_fields:
        field_lines = "\n".join(
            f"- {field_ref.label or default_previous_field_label(field_ref.field_path)} "
            f"(steg {field_ref.from_step}: {field_ref.field_path})"
            for field_ref in step_draft.uses_previous_fields
        )
        instructions = (
            f"{instructions}\n\n"
            "Beakta särskilt följande strukturerade fält i underlaget:\n"
            f"{field_lines}"
        )
    if input_bindings is None and step_draft.uses_form_fields:
        form_lines = "\n".join(
            f"- {field_name}: {{{{ {field_name} }}}}"
            for field_name in step_draft.uses_form_fields
        )
        instructions = (
            f"{instructions}\n\n"
            "Beakta också följande formulärfält vid analysen:\n"
            f"{form_lines}"
        )

    return _append_output_field_guidance(
        instructions=instructions or "",
        output_fields=step_draft.output_fields,
    )


def compile_output_contract(
    output_fields: list[StructuredFieldDraft] | None,
) -> dict[str, Any] | None:
    if not output_fields:
        return None
    return _compile_object_schema(output_fields)


def _derive_input_contract(
    step_draft: NewStepDraft,
    prior_steps: list[StepSpec],
) -> dict[str, Any] | None:
    if step_draft.input_type.value != "json":
        return None
    if step_draft.input_source.value != "previous_step" or not prior_steps:
        return None
    return prior_steps[-1].output_contract


def _resolve_source_reference(
    step_draft: NewStepDraft,
    prior_steps: list[StepSpec],
) -> str | None:
    input_source = step_draft.input_source.value
    input_type = step_draft.input_type.value

    if input_source == "flow_input":
        if input_type == "json":
            return "{{ indata_json }}"
        if input_type in {"document", "file", "audio"}:
            return "{{ step_input.text }}"
        return "{{ indata_text }}"

    if input_source == "previous_step":
        if not prior_steps:
            return None
        previous_step = prior_steps[-1]
        if input_type == "json":
            return f"{{{{ {previous_step.plan_step_ref}.output.structured }}}}"
        if previous_step.output_type == OutputType.JSON:
            return f"{{{{ {previous_step.plan_step_ref}.output.structured }}}}"
        return f"{{{{ {previous_step.plan_step_ref}.output.text }}}}"

    if input_source == "all_previous_steps":
        references = [
            f"{{{{ {step.plan_step_ref}.output.text }}}}" for step in prior_steps
        ]
        return "\n\n".join(references) if references else None

    return None


def _compile_previous_field_sections(
    step_draft: NewStepDraft,
    prior_steps: list[StepSpec],
) -> list[str]:
    sections: list[str] = []
    for field_ref in step_draft.uses_previous_fields:
        if field_ref.from_step < 1 or field_ref.from_step > len(prior_steps):
            continue
        source_step = prior_steps[field_ref.from_step - 1]
        label = field_ref.label or default_previous_field_label(field_ref.field_path)
        sections.append(
            f"{label}: {{{{ {source_step.plan_step_ref}.output.structured.{field_ref.field_path} }}}}"
        )
    return sections


def _compile_previous_output_sections(
    step_draft: NewStepDraft,
    prior_steps: list[StepSpec],
) -> list[str]:
    sections: list[str] = []
    for output_ref in step_draft.uses_previous_outputs:
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
    top_level_fields = [
        field
        for field in output_fields
        if field.name and field.name.casefold() not in normalized_instructions
    ]
    if not top_level_fields:
        return instructions

    field_lines = [f"- {field.name}: {field.description}" for field in top_level_fields]
    return f"{instructions}\n\nRequired JSON fields:\n{chr(10).join(field_lines)}"
