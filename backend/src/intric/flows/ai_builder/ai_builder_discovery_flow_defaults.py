from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import cast

from intric.flows.ai_builder.ai_builder_discovery_families import (
    DiscoveryFamily,
)
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    is_citation_capable_step,
    resolve_document_generation_mode,
    resolve_final_output_artifact,
    resolve_runtime_input_mode,
)
from intric.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep


@dataclass(frozen=True, slots=True)
class FlowInputStepSignature:
    step_order: int
    input_type: str
    output_mode: str
    output_type: str
    max_files: int | None = None


@dataclass(frozen=True, slots=True)
class FlowCapabilityProfile:
    flow_input_steps: tuple[FlowInputStepSignature, ...] = ()
    runtime_input_mode: str | None = None
    runtime_input_settled: bool = False
    document_material_scope: str | None = None
    upload_pattern: str | None = None
    final_output_type: str | None = None
    final_output_mode: str | None = None
    final_output_generation_mode: str | None = None
    runtime_metadata_state: str | None = None
    knowledge_base_step_orders: tuple[int, ...] = ()
    citation_step_orders: tuple[int, ...] = ()
    contract_step_orders: tuple[int, ...] = ()
    variable_binding_step_orders: tuple[int, ...] = ()
    all_previous_steps_orders: tuple[int, ...] = ()
    settled_families: frozenset[DiscoveryFamily] = field(
        default_factory=lambda: frozenset()
    )

    def to_signal_defaults(self) -> dict[str, set[str]]:
        defaults: dict[str, set[str]] = defaultdict(set)

        if self.runtime_input_mode == "documents":
            defaults["input_material_mode"].add("documents")
        elif self.runtime_input_mode == "audio":
            defaults["input_material_mode"].add("audio")
        elif self.runtime_input_mode == "text":
            defaults["input_material_mode"].add("text")
        elif self.runtime_input_mode == "text_and_documents":
            defaults["input_material_mode"].add("text_and_documents")

        if self.upload_pattern is not None:
            defaults["upload_pattern"].add(self.upload_pattern)
        if self.document_material_scope is not None:
            defaults["document_material_scope"].add(self.document_material_scope)
        if self.final_output_mode is not None:
            defaults["final_output_mode"].add(self.final_output_mode)
        if self.final_output_type == "docx":
            defaults["docx_output_mode"].add(
                "template_fill_docx"
                if self.final_output_generation_mode == "template_fill"
                else "generated_docx"
            )
        elif self.final_output_type == "pdf":
            defaults["pdf_generation_mode"].add("generated_pdf")
        if self.runtime_metadata_state is not None:
            defaults["runtime_metadata_fields"].add(self.runtime_metadata_state)

        return {
            question_id: values for question_id, values in defaults.items() if values
        }


def build_flow_discovery_defaults(flow: Flow | None) -> dict[str, set[str]]:
    return build_flow_capability_profile(flow).to_signal_defaults()


def build_flow_capability_profile(flow: Flow | None) -> FlowCapabilityProfile:
    if flow is None:
        return FlowCapabilityProfile()

    steps = sorted(flow.steps, key=lambda step: step.step_order)
    if not steps:
        return FlowCapabilityProfile()

    last_step = steps[-1]
    flow_input_steps = tuple(
        FlowInputStepSignature(
            step_order=step.step_order,
            input_type=_enum_value(step.input_type),
            output_mode=_enum_value(step.output_mode),
            output_type=_enum_value(step.output_type),
            max_files=_runtime_input_max_files(step.input_config),
        )
        for step in steps
        if _enum_value(step.input_source) == "flow_input"
    )

    runtime_input_mode, runtime_input_settled = _derive_runtime_input_mode(
        flow_input_steps
    )
    document_material_scope, upload_pattern = _derive_document_scope(flow_input_steps)
    final_output_mode = resolve_final_output_artifact(
        _enum_value(last_step.output_type)
    )
    final_output_generation_mode = resolve_document_generation_mode(
        output_type=_enum_value(last_step.output_type),
        output_mode=_enum_value(last_step.output_mode),
    )
    runtime_metadata_state = _derive_runtime_metadata_state(flow)
    citation_step_orders = tuple(
        step.step_order
        for step in steps
        if is_citation_capable_step(
            output_type=_enum_value(step.output_type),
            output_mode=_enum_value(step.output_mode),
            output_config=step.output_config,
        )
    )
    contract_step_orders = tuple(
        step.step_order
        for step in steps
        if isinstance(step.input_contract, dict)
        or isinstance(step.output_contract, dict)
    )
    variable_binding_step_orders = tuple(
        step.step_order for step in steps if _has_variable_bindings(step)
    )
    all_previous_steps_orders = tuple(
        step.step_order
        for step in steps
        if _enum_value(step.input_source) == "all_previous_steps"
    )

    settled_families: set[DiscoveryFamily] = set()
    if runtime_input_settled:
        settled_families.add("input_shape")
    if final_output_mode is not None:
        settled_families.add("output_artifact")
    if runtime_metadata_state is not None:
        settled_families.add("runtime_metadata")

    return FlowCapabilityProfile(
        flow_input_steps=flow_input_steps,
        runtime_input_mode=runtime_input_mode,
        runtime_input_settled=runtime_input_settled,
        document_material_scope=document_material_scope,
        upload_pattern=upload_pattern,
        final_output_type=_enum_value(last_step.output_type),
        final_output_mode=final_output_mode,
        final_output_generation_mode=final_output_generation_mode,
        runtime_metadata_state=runtime_metadata_state,
        citation_step_orders=citation_step_orders,
        contract_step_orders=contract_step_orders,
        variable_binding_step_orders=variable_binding_step_orders,
        all_previous_steps_orders=all_previous_steps_orders,
        settled_families=frozenset(settled_families),
    )


def _runtime_input_max_files(
    input_config: FlowPersistedJsonObject | None,
) -> int | None:
    if not isinstance(input_config, dict):
        return None
    runtime_input = input_config.get("runtime_input")
    if not isinstance(runtime_input, dict):
        return None
    max_files = cast(FlowPersistedJsonObject, runtime_input).get("max_files")
    return max_files if isinstance(max_files, int) else None


def _derive_runtime_input_mode(
    flow_input_steps: tuple[FlowInputStepSignature, ...],
) -> tuple[str | None, bool]:
    if not flow_input_steps:
        return None, False

    modes = {
        resolve_runtime_input_mode(signature.input_type)
        for signature in flow_input_steps
    }
    modes.discard(None)
    if not modes:
        return None, False
    if len(modes) == 1:
        return next(iter(modes)), True
    if modes == {"documents", "text"}:
        return "text_and_documents", False
    return "mixed", False


def _derive_document_scope(
    flow_input_steps: tuple[FlowInputStepSignature, ...],
) -> tuple[str | None, str | None]:
    document_steps = tuple(
        signature
        for signature in flow_input_steps
        if resolve_runtime_input_mode(signature.input_type) == "documents"
    )
    if len(document_steps) != 1:
        return None, None
    max_files = document_steps[0].max_files
    if max_files is None:
        return None, None
    if max_files > 1:
        return "multiple_documents_case", "multiple_pdfs"
    return "single_document_case", "single_pdf"


def _derive_runtime_metadata_state(flow: Flow) -> str | None:
    if _has_form_fields(flow):
        return "basic_case_metadata"
    if flow.metadata_json is not None:
        return "no_extra_metadata"
    return None


def _has_variable_bindings(step: FlowStep) -> bool:
    if isinstance(step.input_bindings, dict) and bool(step.input_bindings):
        return True
    if not isinstance(step.output_config, dict):
        return False
    bindings = (
        step.output_config["bindings"] if "bindings" in step.output_config else None
    )
    return isinstance(bindings, dict) and bool(cast(FlowPersistedJsonObject, bindings))


def _enum_value(value: object) -> str:
    raw_value = getattr(value, "value", value)
    return str(raw_value)


def _has_form_fields(flow: Flow) -> bool:
    metadata_json = flow.metadata_json
    if not isinstance(metadata_json, dict):
        return False
    form_schema = metadata_json.get("form_schema")
    if not isinstance(form_schema, dict):
        return False
    form_schema_dict = cast(FlowPersistedJsonObject, form_schema)
    fields = form_schema_dict.get("fields")
    return isinstance(fields, list) and len(cast(list[object], fields)) > 0
