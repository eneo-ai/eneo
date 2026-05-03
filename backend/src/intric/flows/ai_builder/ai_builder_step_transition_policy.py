from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_token_prefix,
    normalize_discovery_text,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_source_material import (
    SourceMaterialBindingStatus,
    iter_compiled_source_material_boundaries,
    question_binding,
    source_material_binding_status,
    source_material_question_for_boundary,
)
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    is_citation_capable_step,
)
from intric.flows.citation_sidecar import resolve_citation_mode
from intric.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)

_TEMPLATE_FILL_ONLY_KEYS = frozenset(
    {"bindings", "template_asset_id", "template_file_id"}
)
_UNFOLDABLE = object()
_ARTIFACT_GENERATION_PREFIXES = (
    "create",
    "generate",
    "format",
    "render",
    "skapa",
    "generera",
    "formattera",
)
_SWEDISH_ARTIFACT_GENERATION_PREFIXES = ("skapa", "generera", "formattera")


@dataclass(frozen=True, slots=True)
class StepNormalizationChange:
    code: str
    field_suffix: str
    message: str
    severity: Literal["info", "warning", "error"] = "info"


def normalize_ai_builder_spec(
    spec: FlowDraftSpecCore,
    *,
    terminal_output_type: OutputType | None = None,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    spec, topology_changes = normalize_ai_builder_step_topology(
        spec,
        terminal_output_type=terminal_output_type,
    )
    normalized_steps: list[StepSpec] = []
    changes: list[tuple[StepSpec, StepNormalizationChange]] = list(topology_changes)
    mutated = False

    for step in spec.steps:
        normalized_step, step_changes = normalize_ai_builder_step(step)
        normalized_steps.append(normalized_step)
        mutated = mutated or normalized_step is not step
        changes.extend((normalized_step, change) for change in step_changes)

    if not mutated:
        return spec, changes
    return spec.model_copy(update={"steps": normalized_steps}), changes


def normalize_ai_builder_step_topology(
    spec: FlowDraftSpecCore,
    *,
    terminal_output_type: OutputType | None = None,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    """Normalize redundant Flow graph mechanics before quality validation.

    AI Builder create/edit tasks are allowed to describe semantic data flow, but
    the backend owns token-sensitive topology choices. Most generated linear
    flows do not need `all_previous_steps`; it duplicates context and triggers
    noisy quality warnings. Keep true fan-in when a prompt explicitly references
    several earlier steps, otherwise compile to the lean adjacent edge.

    Artifact flows that cross a structured JSON boundary also need explicit
    source-material underlag. Without that binding, later document-rendering
    steps can see only metadata JSON and lose the transcript or source file text.
    """

    spec, artifact_tail_changes = _normalize_terminal_artifact_tail(
        spec,
        terminal_output_type=terminal_output_type,
    )
    spec, artifact_body_changes = _normalize_pre_terminal_artifact_body_step(
        spec,
        terminal_output_type=terminal_output_type,
    )
    step_refs = {step.plan_step_ref: index + 1 for index, step in enumerate(spec.steps)}
    form_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    all_previous_indexes = [
        index
        for index, step in enumerate(spec.steps)
        if step.input_source == InputSource.ALL_PREVIOUS_STEPS
    ]
    last_all_previous_index = (
        all_previous_indexes[-1] if len(all_previous_indexes) > 1 else None
    )
    normalized_steps: list[StepSpec] = []
    changes: list[tuple[StepSpec, StepNormalizationChange]] = [
        *artifact_tail_changes,
        *artifact_body_changes,
    ]
    mutated = bool(changes)

    for index, step in enumerate(spec.steps):
        if _can_rewire_all_previous_to_previous_step(
            step=step,
            step_index=index,
            step_refs=step_refs,
            form_fields=form_fields,
            repeated_all_previous=len(all_previous_indexes) > 1,
            preserve_as_final_fan_in=index == last_all_previous_index,
        ):
            normalized_step = step.model_copy(
                update={"input_source": InputSource.PREVIOUS_STEP}
            )
            normalized_steps.append(normalized_step)
            mutated = True
            changes.append(
                (
                    normalized_step,
                    StepNormalizationChange(
                        code="input_source_all_previous_rewired",
                        field_suffix="input_source",
                        message=(
                            "Rewired redundant all_previous_steps to previous_step "
                            "because no explicit multi-step fan-in was required."
                        ),
                    ),
                )
            )
            continue
        normalized_steps.append(step)

    normalized_spec = (
        spec if not mutated else spec.model_copy(update={"steps": normalized_steps})
    )
    normalized_spec, source_material_changes = _normalize_source_material_underlag(
        normalized_spec
    )
    changes.extend(source_material_changes)
    mutated = mutated or bool(source_material_changes)

    if not mutated:
        return spec, changes
    return normalized_spec, changes


def _normalize_source_material_underlag(
    spec: FlowDraftSpecCore,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    updated_steps = list(spec.steps)
    changes: list[tuple[StepSpec, StepNormalizationChange]] = []

    for boundary in iter_compiled_source_material_boundaries(spec):
        if (
            source_material_binding_status(boundary)
            is not SourceMaterialBindingStatus.NEEDS_COMPLETION
        ):
            continue
        step_index = next(
            index
            for index, candidate in enumerate(spec.steps)
            if candidate is boundary.step
        )
        existing_question = question_binding(boundary.step.input_bindings)
        normalized_bindings = dict(boundary.step.input_bindings or {})
        normalized_bindings["question"] = source_material_question_for_boundary(
            boundary,
            existing_question=existing_question,
        )
        normalized_step = boundary.step.model_copy(
            update={
                "input_type": InputType.TEXT,
                "input_bindings": normalized_bindings,
            }
        )
        updated_steps[step_index] = normalized_step
        changes.append(
            (
                normalized_step,
                StepNormalizationChange(
                    code="source_material_underlag_completed",
                    field_suffix="input_bindings.question",
                    message=(
                        "Completed source-material underlag so the step receives "
                        "the immediate structured result and the earlier source text."
                    ),
                ),
            )
        )

    if not changes:
        return spec, []
    return spec.model_copy(update={"steps": updated_steps}), changes


def _normalize_pre_terminal_artifact_body_step(
    spec: FlowDraftSpecCore,
    *,
    terminal_output_type: OutputType | None,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    if terminal_output_type not in {OutputType.PDF, OutputType.DOCX}:
        return spec, []
    output_type = cast(OutputType, terminal_output_type)
    if len(spec.steps) < 2:
        return spec, []

    terminal_step = spec.steps[-1]
    if terminal_step.output_type != output_type:
        return spec, []

    normalized_steps: list[StepSpec] = []
    changes: list[tuple[StepSpec, StepNormalizationChange]] = []
    for step in spec.steps[:-1]:
        if not _looks_like_artifact_body_step(step, output_type=output_type):
            normalized_steps.append(step)
            continue

        normalized_body = step.model_copy(
            update={
                "name": _artifact_body_step_name(
                    output_type=output_type,
                    source_text=_step_instruction_text(step),
                ),
                "assistant_spec": _artifact_body_step_assistant(
                    step=step,
                    output_type=output_type,
                ),
            }
        )
        normalized_steps.append(normalized_body)
        changes.append(
            (
                normalized_body,
                StepNormalizationChange(
                    code="pre_terminal_artifact_body_step_renamed",
                    field_suffix="name",
                    message=(
                        "Renamed a non-terminal artifact-generation helper so "
                        "it prepares document content while the terminal step "
                        "owns file creation."
                    ),
                ),
            )
        )

    if not changes:
        return spec, []

    return spec.model_copy(
        update={"steps": [*normalized_steps, terminal_step]}
    ), changes


def _looks_like_artifact_body_step(
    step: StepSpec,
    *,
    output_type: OutputType,
) -> bool:
    if step.output_type != OutputType.TEXT:
        return False
    if step.output_mode != OutputMode.PASS_THROUGH:
        return False
    normalized = normalize_discovery_text(_step_instruction_text(step))
    if not _mentions_artifact_type(normalized, output_type=output_type):
        return False
    return contains_any_token_prefix(normalized, _ARTIFACT_GENERATION_PREFIXES)


def _mentions_artifact_type(text: str, *, output_type: OutputType) -> bool:
    if output_type == OutputType.DOCX:
        return contains_any_token_prefix(text, ("docx", "word"))
    if output_type == OutputType.PDF:
        return contains_any_token_prefix(text, ("pdf",))
    return False


def _artifact_body_step_name(*, output_type: OutputType, source_text: str) -> str:
    normalized = normalize_discovery_text(source_text)
    artifact_name = output_type.value.upper()
    if contains_any_token_prefix(normalized, _SWEDISH_ARTIFACT_GENERATION_PREFIXES):
        return f"Förbered {artifact_name}-innehåll"
    return f"Prepare {artifact_name} content"


def _artifact_body_step_assistant(
    *,
    step: StepSpec,
    output_type: OutputType,
) -> AssistantSpec:
    source_text = _step_instruction_text(step)
    prefix = _artifact_body_step_instruction_prefix(
        output_type=output_type,
        source_text=source_text,
    )
    instructions = step.assistant_spec.instructions.strip()
    return step.assistant_spec.model_copy(
        update={
            "instructions": (f"{prefix}\n\n{instructions}" if instructions else prefix)
        }
    )


def _artifact_body_step_instruction_prefix(
    *,
    output_type: OutputType,
    source_text: str,
) -> str:
    artifact_name = output_type.value.upper()
    normalized = normalize_discovery_text(source_text)
    if contains_any_token_prefix(normalized, _SWEDISH_ARTIFACT_GENERATION_PREFIXES):
        return (
            f"Förbered textinnehållet som terminalsteget ska rendera till "
            f"{artifact_name}. Terminalsteget skapar själva {artifact_name}-filen."
        )
    return (
        f"Prepare the text content that the terminal step will render as "
        f"{artifact_name}. The terminal step creates the actual {artifact_name} file."
    )


def _step_instruction_text(step: StepSpec) -> str:
    return f"{step.name} {step.assistant_spec.instructions}"


def _normalize_terminal_artifact_tail(
    spec: FlowDraftSpecCore,
    *,
    terminal_output_type: OutputType | None,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    """Keep artifact-output plans terminal on the requested artifact.

    LLMs often satisfy "make the final output PDF/DOCX" by inserting a new
    artifact-producing helper step before an existing "create final result"
    text step. That is semantically close, but the Flow runtime returns the
    final step. Fold that helper into the terminal text step instead of asking
    the model to retry, preserving scoped-edit target refs and reducing repair
    loops.
    """

    if terminal_output_type not in {OutputType.PDF, OutputType.DOCX}:
        return spec, []
    if len(spec.steps) < 2:
        return spec, []

    artifact_step = spec.steps[-2]
    terminal_step = spec.steps[-1]
    if terminal_step.output_type == terminal_output_type:
        return spec, []
    if artifact_step.output_type != terminal_output_type:
        return spec, []
    if terminal_step.output_type != OutputType.TEXT:
        return spec, []
    if terminal_step.output_mode != OutputMode.PASS_THROUGH:
        return spec, []
    if terminal_step.input_source not in {
        InputSource.PREVIOUS_STEP,
        InputSource.ALL_PREVIOUS_STEPS,
    }:
        return spec, []

    folded_input_bindings = _fold_artifact_helper_input_bindings(
        spec=spec,
        artifact_step=artifact_step,
        terminal_step=terminal_step,
    )
    if folded_input_bindings is _UNFOLDABLE:
        return spec, []

    promoted_terminal = terminal_step.model_copy(
        update={
            "assistant_spec": _fold_artifact_helper_assistant(
                artifact_step=artifact_step,
                terminal_step=terminal_step,
            ),
            "input_source": artifact_step.input_source,
            "input_type": artifact_step.input_type,
            "input_bindings": folded_input_bindings,
            "input_contract": artifact_step.input_contract,
            "input_config": artifact_step.input_config,
            "output_type": terminal_output_type,
            "output_mode": artifact_step.output_mode,
            "output_contract": artifact_step.output_contract,
            "output_config": artifact_step.output_config,
        }
    )
    normalized_steps = [*spec.steps[:-2], promoted_terminal]
    change = StepNormalizationChange(
        code="terminal_artifact_helper_folded",
        field_suffix="steps",
        message=(
            "Folded an inserted artifact helper into the terminal step so the "
            "flow returns the requested final artifact."
        ),
    )
    return spec.model_copy(update={"steps": normalized_steps}), [
        (promoted_terminal, change)
    ]


def _fold_artifact_helper_assistant(
    *,
    artifact_step: StepSpec,
    terminal_step: StepSpec,
) -> AssistantSpec:
    helper_instructions = artifact_step.assistant_spec.instructions.strip()
    terminal_instructions = terminal_step.assistant_spec.instructions.strip()
    if helper_instructions and terminal_instructions:
        instructions = f"{terminal_instructions}\n\n{helper_instructions}"
    else:
        instructions = terminal_instructions or helper_instructions

    updates: dict[str, Any] = {"instructions": instructions}
    if not terminal_step.assistant_spec.model_ref:
        updates["model_ref"] = artifact_step.assistant_spec.model_ref
    if (
        not terminal_step.assistant_spec.knowledge_refs
        and not terminal_step.assistant_spec.mcp_server_refs
        and not terminal_step.assistant_spec.mcp_tool_refs
    ):
        updates.update(
            {
                "knowledge_refs": artifact_step.assistant_spec.knowledge_refs,
                "mcp_server_refs": artifact_step.assistant_spec.mcp_server_refs,
                "mcp_tool_refs": artifact_step.assistant_spec.mcp_tool_refs,
            }
        )
    return terminal_step.assistant_spec.model_copy(update=updates)


def _fold_artifact_helper_input_bindings(
    *,
    spec: FlowDraftSpecCore,
    artifact_step: StepSpec,
    terminal_step: StepSpec,
) -> dict[str, Any] | None | object:
    if terminal_step.input_bindings is None:
        return artifact_step.input_bindings

    replacement = _artifact_helper_source_binding(
        spec=spec,
        artifact_step=artifact_step,
    )
    if replacement is None and _bindings_reference_step(
        terminal_step.input_bindings,
        artifact_step.plan_step_ref,
    ):
        return _UNFOLDABLE
    if replacement is None:
        return terminal_step.input_bindings
    return cast(
        dict[str, Any],
        _rewrite_binding_step_references(
            terminal_step.input_bindings,
            step_ref=artifact_step.plan_step_ref,
            replacement=replacement,
        ),
    )


def _artifact_helper_source_binding(
    *,
    spec: FlowDraftSpecCore,
    artifact_step: StepSpec,
) -> str | None:
    question = _question_binding(artifact_step)
    if question:
        return question
    if artifact_step.input_source != InputSource.PREVIOUS_STEP:
        return None
    artifact_index = spec.steps.index(artifact_step)
    if artifact_index == 0:
        return None
    previous_step = spec.steps[artifact_index - 1]
    output_path = (
        "structured" if previous_step.output_type == OutputType.JSON else "text"
    )
    return f"{{{{ {previous_step.plan_step_ref}.output.{output_path} }}}}"


def _bindings_reference_step(value: Any, step_ref: str) -> bool:
    if isinstance(value, str):
        return _step_output_reference_pattern(step_ref).search(value) is not None
    if isinstance(value, dict):
        mapping = cast(Mapping[Any, Any], value)
        return any(
            _bindings_reference_step(child, step_ref) for child in mapping.values()
        )
    if isinstance(value, list):
        children = cast(list[Any], value)
        return any(_bindings_reference_step(child, step_ref) for child in children)
    return False


def _rewrite_binding_step_references(
    value: Any,
    *,
    step_ref: str,
    replacement: str,
) -> Any:
    if isinstance(value, str):
        return _step_output_reference_pattern(step_ref).sub(replacement, value)
    if isinstance(value, dict):
        mapping = cast(Mapping[Any, Any], value)
        rewritten: dict[Any, Any] = {}
        for key, child in mapping.items():
            rewritten[key] = _rewrite_binding_step_references(
                child,
                step_ref=step_ref,
                replacement=replacement,
            )
        return rewritten
    if isinstance(value, list):
        children = cast(list[Any], value)
        rewritten_list: list[Any] = []
        for child in children:
            rewritten_list.append(
                _rewrite_binding_step_references(
                    child,
                    step_ref=step_ref,
                    replacement=replacement,
                )
            )
        return rewritten_list
    return value


def _step_output_reference_pattern(step_ref: str) -> re.Pattern[str]:
    return re.compile(
        r"{{\s*"
        + re.escape(step_ref)
        + r"\.output\.(?:text|structured|json|document|file|pdf|docx)\s*}}"
    )


def _can_rewire_all_previous_to_previous_step(
    *,
    step: StepSpec,
    step_index: int,
    step_refs: dict[str, int],
    form_fields: set[str],
    repeated_all_previous: bool,
    preserve_as_final_fan_in: bool,
) -> bool:
    if step_index == 0:
        return False
    if step.input_source != InputSource.ALL_PREVIOUS_STEPS:
        return False

    question = _question_binding(step)
    if question is None:
        return repeated_all_previous and not preserve_as_final_fan_in

    references = analyze_template(
        question,
        step_refs=step_refs,
        form_field_names=form_fields,
    )
    referenced_step_orders = {
        reference.step_order
        for reference in references
        if reference.kind is TemplateReferenceKind.STEP
        and reference.step_order is not None
    }
    if len(referenced_step_orders) > 1:
        return False

    previous_step_order = step_index
    if referenced_step_orders == {previous_step_order}:
        return True
    if not referenced_step_orders:
        return repeated_all_previous and not preserve_as_final_fan_in
    return False


def normalize_ai_builder_step(
    step: StepSpec,
) -> tuple[StepSpec, list[StepNormalizationChange]]:
    changes: list[StepNormalizationChange] = []
    if not all(
        hasattr(step, attribute)
        for attribute in ("output_mode", "output_type", "output_config", "model_copy")
    ):
        return step, changes

    output_mode = step.output_mode
    output_type = step.output_type
    output_config = _as_output_config_dict(step.output_config)
    updates: dict[str, Any] = {}

    if output_mode == OutputMode.TEMPLATE_FILL and output_type != OutputType.DOCX:
        output_mode = OutputMode.PASS_THROUGH
        updates["output_mode"] = output_mode
        changes.append(
            StepNormalizationChange(
                code="output_mode_template_fill_reset",
                field_suffix="output_mode",
                message=(
                    "Template fill reset to pass_through because only DOCX steps can keep "
                    "output_mode 'template_fill'."
                ),
            )
        )

    if output_config is not None:
        next_output_config = dict(output_config)
        if output_mode != OutputMode.TEMPLATE_FILL:
            removed_template_keys = sorted(
                key for key in _TEMPLATE_FILL_ONLY_KEYS if key in next_output_config
            )
            for key in removed_template_keys:
                del next_output_config[key]
            if removed_template_keys:
                changes.append(
                    StepNormalizationChange(
                        code="output_config_template_fill_keys_cleared",
                        field_suffix="output_config",
                        message=(
                            "Removed template-fill-only output_config fields because this step "
                            "no longer uses output_mode 'template_fill'."
                        ),
                    )
                )

        citation_mode = resolve_citation_mode(next_output_config)
        if citation_mode == "inline_inref_sidecar" and not is_citation_capable_step(
            output_type=str(output_type),
            output_mode=str(output_mode),
            output_config=next_output_config,
        ):
            del next_output_config["citation_mode"]
            changes.append(
                StepNormalizationChange(
                    code="output_config_citation_mode_cleared",
                    field_suffix="output_config.citation_mode",
                    message=(
                        "Removed citation_mode because only LLM-backed text steps can keep "
                        "inline citation tracking."
                    ),
                )
            )

        normalized_output_config = next_output_config or None
        if normalized_output_config != step.output_config:
            updates["output_config"] = normalized_output_config

    if not updates:
        return step, changes
    return step.model_copy(update=updates), changes


def supports_inline_inref_citation(
    *,
    output_type: OutputType,
    output_mode: OutputMode,
) -> bool:
    return is_citation_capable_step(
        output_type=str(output_type),
        output_mode=str(output_mode),
        output_config={"citation_mode": "inline_inref_sidecar"},
    )


def _as_output_config_dict(output_config: Any) -> dict[str, Any] | None:
    if not isinstance(output_config, dict):
        return None
    typed_output_config = cast(dict[object, Any], output_config)
    normalized: dict[str, Any] = {}
    for key, value in typed_output_config.items():
        normalized[str(key)] = value
    return normalized


def _question_binding(step: StepSpec) -> str | None:
    if not isinstance(step.input_bindings, dict):
        return None
    question = step.input_bindings.get("question")
    if isinstance(question, str) and question.strip():
        return question
    return None
