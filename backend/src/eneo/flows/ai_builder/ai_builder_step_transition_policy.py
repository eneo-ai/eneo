from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_token_prefix,
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_source_material import (
    SourceMaterialBindingStatus,
    iter_compiled_source_material_boundaries,
    source_material_binding_status,
    source_material_bindings_for_boundary,
)
from eneo.flows.citation_sidecar import resolve_citation_mode
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_capability_manifest import is_citation_capable_step
from eneo.flows.input_binding_contract_rules import (
    SOURCE_REFS_BINDING_KEY,
    dedupe_source_refs,
    effective_question_binding,
    source_ref_bindings,
)
from eneo.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)

_TEMPLATE_FILL_ONLY_KEYS = frozenset(
    {"bindings", "template_asset_id", "template_file_id"}
)
_ARTIFACT_GENERATION_PREFIXES = (
    "create",
    "generate",
    "format",
    "render",
    "skapa",
    "generera",
    "formattera",
)


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
    disambiguate_duplicate_step_names: bool = False,
    ui_language: str | None = None,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    spec, topology_changes = normalize_ai_builder_step_topology(
        spec,
        terminal_output_type=terminal_output_type,
        disambiguate_duplicate_step_names=disambiguate_duplicate_step_names,
        ui_language=ui_language,
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
    disambiguate_duplicate_step_names: bool = False,
    ui_language: str | None = None,
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

    spec, artifact_body_changes = _normalize_pre_terminal_artifact_body_step(
        spec,
        terminal_output_type=terminal_output_type,
        ui_language=ui_language,
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
        normalized_spec,
        ui_language=ui_language,
    )
    changes.extend(source_material_changes)
    mutated = mutated or bool(source_material_changes)

    if disambiguate_duplicate_step_names:
        normalized_spec, step_name_changes = _normalize_duplicate_step_names(
            normalized_spec
        )
        changes.extend(step_name_changes)
        mutated = mutated or bool(step_name_changes)

    if not mutated:
        return spec, changes
    return normalized_spec, changes


def _normalize_duplicate_step_names(
    spec: FlowDraftSpecCore,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    used_names: set[str] = set()
    updated_steps: list[StepSpec] = []
    changes: list[tuple[StepSpec, StepNormalizationChange]] = []

    for step in spec.steps:
        next_name = _unique_step_name(step.name, used_names=used_names)
        if next_name == step.name:
            used_names.add(_step_name_key(next_name))
            updated_steps.append(step)
            continue

        normalized_step = step.model_copy(update={"name": next_name})
        used_names.add(_step_name_key(next_name))
        updated_steps.append(normalized_step)
        changes.append(
            (
                normalized_step,
                StepNormalizationChange(
                    code="duplicate_step_name_disambiguated",
                    field_suffix="name",
                    message=(
                        "Disambiguated a duplicate step name so the compiled "
                        "flow remains publishable without another LLM repair pass."
                    ),
                ),
            )
        )

    if not changes:
        return spec, []
    return spec.model_copy(update={"steps": updated_steps}), changes


def _unique_step_name(name: str, *, used_names: set[str]) -> str:
    base_name = name.strip() or "Step"
    if _step_name_key(base_name) not in used_names:
        return base_name

    suffix = 2
    while True:
        candidate = f"{base_name} ({suffix})"
        if _step_name_key(candidate) not in used_names:
            return candidate
        suffix += 1


def _step_name_key(name: str) -> str:
    return name.strip().casefold()


def _normalize_source_material_underlag(
    spec: FlowDraftSpecCore,
    *,
    ui_language: str | None = None,
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
        normalized_bindings = source_material_bindings_for_boundary(
            boundary,
            ui_language=ui_language,
        )
        updates: dict[str, Any] = {
            "input_type": InputType.TEXT,
            "input_bindings": normalized_bindings,
        }
        normalized_step = boundary.step.model_copy(update=updates)
        updated_steps[step_index] = normalized_step
        changes.append(
            (
                normalized_step,
                StepNormalizationChange(
                    code="source_material_underlag_completed",
                    field_suffix="input_bindings.source_refs",
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
    ui_language: str | None,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    if terminal_output_type not in {OutputType.PDF, OutputType.DOCX}:
        return spec, []
    output_type = cast(OutputType, terminal_output_type)
    if len(spec.steps) < 2:
        return spec, []

    terminal_step = spec.steps[-1]
    if terminal_step.output_type != output_type:
        return spec, []

    body_step_indexes = {
        index
        for index, step in enumerate(spec.steps[:-1])
        if _looks_like_artifact_body_step(step, output_type=output_type)
    }
    if not body_step_indexes:
        return spec, []

    if len(body_step_indexes) > 1:
        # Several pre-terminal steps look like artifact-body work. Flattening
        # them all to the single canonical name only manufactures confusing
        # "(2)" collisions, so keep the planner's distinct names; the terminal
        # step still owns file creation.
        return spec, []

    used_step_names = {
        _step_name_key(step.name)
        for index, step in enumerate(spec.steps)
        if index not in body_step_indexes
    }
    normalized_steps: list[StepSpec] = []
    changes: list[tuple[StepSpec, StepNormalizationChange]] = []
    for index, step in enumerate(spec.steps[:-1]):
        if index not in body_step_indexes:
            normalized_steps.append(step)
            continue

        body_step_name = _unique_step_name(
            _artifact_body_step_name(
                output_type=output_type,
                ui_language=ui_language,
            ),
            used_names=used_step_names,
        )
        used_step_names.add(_step_name_key(body_step_name))
        normalized_body = step.model_copy(
            update={
                "name": body_step_name,
                "assistant_spec": _artifact_body_step_assistant(
                    step=step,
                    output_type=output_type,
                    ui_language=ui_language,
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


def _artifact_body_step_name(
    *,
    output_type: OutputType,
    ui_language: str | None,
) -> str:
    artifact_name = output_type.value.upper()
    if _uses_english_ui(ui_language):
        return f"Prepare {artifact_name} content"
    return f"Förbered {artifact_name}-innehåll"


def _artifact_body_step_assistant(
    *,
    step: StepSpec,
    output_type: OutputType,
    ui_language: str | None,
) -> AssistantSpec:
    prefix = _artifact_body_step_instruction_prefix(
        output_type=output_type,
        ui_language=ui_language,
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
    ui_language: str | None,
) -> str:
    artifact_name = output_type.value.upper()
    if _uses_english_ui(ui_language):
        return (
            f"Prepare the text content that the terminal step will render as "
            f"{artifact_name}. The terminal step creates the actual {artifact_name} file."
        )
    return (
        f"Förbered textinnehållet som terminalsteget ska rendera till "
        f"{artifact_name}. Terminalsteget skapar själva {artifact_name}-filen."
    )


def _uses_english_ui(ui_language: str | None) -> bool:
    return ui_language is not None and ui_language.casefold().startswith("en")


def _step_instruction_text(step: StepSpec) -> str:
    return f"{step.name} {step.assistant_spec.instructions}"


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

    question = effective_question_binding(step.input_bindings)
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
            output_type=output_type,
            output_mode=FlowOutputMode(output_mode.value),
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

    normalized_input_bindings = _dedupe_input_binding_source_refs(step.input_bindings)
    if normalized_input_bindings != step.input_bindings:
        updates["input_bindings"] = normalized_input_bindings
        changes.append(
            StepNormalizationChange(
                code="source_refs_deduped",
                field_suffix="input_bindings.source_refs",
                message=(
                    "Collapsed duplicate source_refs so the step receives each "
                    "source material reference once."
                ),
            )
        )

    if (
        effective_question_binding(step.input_bindings) is not None
        and step.input_contract is not None
    ):
        updates["input_contract"] = None
        changes.append(
            StepNormalizationChange(
                code="explicit_question_input_contract_cleared",
                field_suffix="input_contract",
                message=(
                    "Removed input_contract because the explicit question binding "
                    "supplies rendered text, not the inherited structured object."
                ),
            )
        )
    elif (
        step.input_source == InputSource.ALL_PREVIOUS_STEPS
        and step.input_contract is not None
    ):
        updates["input_contract"] = None
        changes.append(
            StepNormalizationChange(
                code="all_previous_input_contract_cleared",
                field_suffix="input_contract",
                message=(
                    "Removed input_contract because all_previous_steps provides "
                    "concatenated text, not one contract-shaped input object."
                ),
            )
        )

    if not updates:
        return step, changes
    return step.model_copy(update=updates), changes


def _dedupe_input_binding_source_refs(
    input_bindings: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if input_bindings is None or SOURCE_REFS_BINDING_KEY not in input_bindings:
        return input_bindings
    source_refs = source_ref_bindings(input_bindings)
    deduped_source_refs = dedupe_source_refs(source_refs)
    if len(deduped_source_refs) == len(source_refs):
        return input_bindings
    normalized = dict(input_bindings)
    normalized[SOURCE_REFS_BINDING_KEY] = [
        ref.binding_payload() for ref in deduped_source_refs
    ]
    return normalized


def supports_inline_inref_citation(
    *,
    output_type: OutputType,
    output_mode: OutputMode,
) -> bool:
    return is_citation_capable_step(
        output_type=output_type,
        output_mode=FlowOutputMode(output_mode.value),
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
