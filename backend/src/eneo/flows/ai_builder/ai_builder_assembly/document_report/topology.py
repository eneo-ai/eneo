from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from eneo.flows.ai_builder.ai_builder_assembly.plan import DocumentReportSectionSource
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    missing_structured_output_path,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSectionContract,
    RequestedOutputSections,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_variable_definitions import form_field_reference_expression
from eneo.flows.input_binding_contract_rules import (
    SourceRefBinding,
    item_template_field_names,
    source_ref_bindings,
)
from eneo.flows.source_identity import (
    RUNTIME_MANAGED_SOURCE_FIELDS,
    RUNTIME_SOURCE_EXTRACTION_WARNINGS_FIELD,
)

COMPOSE_SECTION_TITLE_KEY = "section_title"
COMPOSE_SECTION_BODY_KEY = "section_body"
COMPOSE_SOURCE_LABEL_KEY = "source_label"
COMPOSE_REPORT_TITLE_KEY = "report_title"
COMPOSE_OVERALL_OVERVIEW_KEY = "overall_overview"
DIRECT_COMPOSE_SCALAR_FIELD_TYPES = frozenset({"string", "number", "boolean"})
_CANONICAL_SECTION_FIELDS = frozenset(
    {
        COMPOSE_SECTION_TITLE_KEY,
        COMPOSE_SECTION_BODY_KEY,
        COMPOSE_SOURCE_LABEL_KEY,
    }
)


def requested_output_section_contracts(
    requested: RequestedOutputSections,
) -> tuple[RequestedOutputSectionContract, ...]:
    if not requested.high_confidence:
        return ()
    return tuple(
        RequestedOutputSectionContract(
            original_label=original_label,
            derived_key=f"requested_section_{index}",
        )
        for index, original_label in enumerate(requested.sections, start=1)
    )


def bind_document_report_compose_inputs(
    *,
    step: StepSpec,
    prior_steps: list[StepSpec],
    form_field_refs: tuple[str, ...],
    requested_output_section_contracts: tuple[RequestedOutputSectionContract, ...],
    document_report_section_source: DocumentReportSectionSource | None,
    ui_language: str | None,
) -> StepSpec:
    prior_steps_by_ref = {prior.plan_step_ref: prior for prior in prior_steps}
    section_step = (
        prior_steps_by_ref.get(document_report_section_source.producer_ref)
        if document_report_section_source is not None
        else None
    )
    section_array = (
        document_report_section_source.field_name
        if document_report_section_source is not None
        else None
    )
    if document_report_section_source is not None and (
        section_step is None
        or section_array not in _schema_properties(section_step.output_contract)
    ):
        raise ValueError(
            "Compiler-lowered report section source is missing from the plan."
        )
    overview_step = _find_compose_overview_source(prior_steps)
    if (section_step is None or section_array is None) and overview_step is None:
        return step

    section_label_by_key = {
        contract.derived_key: contract.original_label
        for contract in requested_output_section_contracts
    }
    source_refs: list[dict[str, object]] = []
    if section_step is not None and section_array is not None:
        section_schema = _schema_properties(section_step.output_contract).get(
            section_array
        )
        source_refs.append(
            SourceRefBinding(
                step_ref=section_step.plan_step_ref,
                output="structured",
                field_path=(section_array,),
                item_template=_compose_section_item_template(
                    ui_language,
                    item_properties=_array_item_properties(section_schema),
                    section_label_by_key=section_label_by_key,
                ),
            ).binding_payload()
        )
        section_step_index = prior_steps.index(section_step)
        for producer in prior_steps[section_step_index + 1 :]:
            if producer is overview_step or producer.output_type != OutputType.JSON:
                continue
            for field_name, field_schema in _schema_properties(
                producer.output_contract
            ).items():
                source_refs.append(
                    _compose_additional_field_ref(
                        step_ref=producer.plan_step_ref,
                        field_name=field_name,
                        field_schema=field_schema,
                        label=None,
                    ).binding_payload()
                )
    question_parts = [
        _compose_report_title_question(
            overview_step=overview_step,
            ui_language=ui_language,
        )
    ]
    if form_field_refs:
        question_parts.append(
            "\n".join(
                f"{field_name}: {form_field_reference_expression(field_name)}"
                for field_name in form_field_refs
            )
        )
    if overview_step is not None:
        source_refs.append(
            SourceRefBinding(
                step_ref=overview_step.plan_step_ref,
                output="structured",
                field_path=(COMPOSE_OVERALL_OVERVIEW_KEY,),
                label=_compose_overview_label(ui_language),
            ).binding_payload()
        )
        for field_name, field_schema in _schema_properties(
            overview_step.output_contract
        ).items():
            if field_name in {
                COMPOSE_REPORT_TITLE_KEY,
                COMPOSE_OVERALL_OVERVIEW_KEY,
            }:
                continue
            source_refs.append(
                _compose_additional_field_ref(
                    step_ref=overview_step.plan_step_ref,
                    field_name=field_name,
                    field_schema=field_schema,
                    label=section_label_by_key.get(field_name),
                ).binding_payload()
            )
    retained_producer_index = (
        prior_steps.index(section_step)
        if section_step is not None
        else prior_steps.index(overview_step)
        if overview_step is not None
        else None
    )
    referenced_step_refs = {
        ref.step_ref for ref in source_ref_bindings({"source_refs": source_refs})
    }
    if retained_producer_index is None or any(
        producer.plan_step_ref not in referenced_step_refs
        for producer in prior_steps[retained_producer_index:]
        if producer.output_type == OutputType.JSON
        and producer.output_contract is not None
    ):
        raise ValueError(
            "Compiler-lowered report compose omitted a retained structured producer."
        )
    return step.model_copy(
        update={
            "input_bindings": {
                "question": "\n\n".join(question_parts),
                "source_refs": source_refs,
            },
            "input_contract": None,
        }
    )


def is_bound_document_report_compose_topology(
    spec: FlowDraftSpecCore,
    step: StepSpec,
) -> bool:
    if (
        step.input_source != InputSource.PREVIOUS_STEP
        or step.input_type != InputType.TEXT
        or step.output_type != OutputType.TEXT
        or step.output_mode != OutputMode.COMPOSE_TEXT
        or step.plan_step_ref not in (spec.document_body_writer_step_refs or ())
    ):
        return False
    step_index = next(
        (index for index, candidate in enumerate(spec.steps) if candidate is step),
        None,
    )
    if step_index is None or step_index + 2 != len(spec.steps):
        return False
    renderer = spec.steps[step_index + 1]
    if (
        renderer.input_source != InputSource.PREVIOUS_STEP
        or renderer.input_type != InputType.TEXT
        or renderer.output_mode != OutputMode.RENDER_VERBATIM
        or renderer.output_type not in {OutputType.DOCX, OutputType.PDF}
    ):
        return False
    prior_steps = spec.steps[:step_index]
    if (
        not prior_steps
        or prior_steps[0].input_source != InputSource.FLOW_INPUT
        or prior_steps[0].input_type not in {InputType.DOCUMENT, InputType.FILE}
        or prior_steps[0].output_type != OutputType.JSON
        or any(
            prior.input_source != InputSource.PREVIOUS_STEP
            or prior.input_type != InputType.JSON
            or prior.output_type != OutputType.JSON
            for prior in prior_steps[1:]
        )
    ):
        return False
    prior_steps_by_ref = {prior.plan_step_ref: prior for prior in prior_steps}
    refs = source_ref_bindings(step.input_bindings)
    if not refs or any(
        ref.output != "structured"
        or not ref.field_path
        or (producer := prior_steps_by_ref.get(ref.step_ref)) is None
        or producer.output_contract is None
        or missing_structured_output_path(
            producer.output_contract,
            ".".join(ref.field_path),
        )
        is not None
        for ref in refs
    ):
        return False

    section_source = _bound_document_report_section_source(refs)
    canonical_producer_indexes: list[int] = []
    if section_source is not None:
        section_producer = prior_steps_by_ref.get(section_source.producer_ref)
        if section_producer is None or section_producer.output_contract is None:
            return False
        section_ref = refs[0]
        section_schema = _schema_properties(section_producer.output_contract).get(
            section_source.field_name
        )
        item_properties = _array_item_properties(section_schema)
        required_template_fields = _required_section_template_field_names(
            item_properties
        )
        if (
            section_schema is None
            or section_ref.item_template is None
            or not required_template_fields
            or not required_template_fields.issubset(
                item_template_field_names(section_ref.item_template)
            )
            or "source_file_id" in item_template_field_names(section_ref.item_template)
        ):
            return False
        if not _CANONICAL_SECTION_FIELDS.issubset(item_properties):
            if (
                section_producer is not prior_steps[0]
                or section_source.field_name != "documents"
                or not all(
                    _schema_declares_direct_compose_scalar(field_schema)
                    for field_name, field_schema in item_properties.items()
                    if field_name not in RUNTIME_MANAGED_SOURCE_FIELDS
                )
            ):
                return False
        canonical_producer_indexes.append(prior_steps.index(section_producer))
    for ref in refs:
        producer = prior_steps_by_ref[ref.step_ref]
        assert producer.output_contract is not None
        producer_fields = _schema_properties(producer.output_contract)
        if (
            ref.field_path == (COMPOSE_OVERALL_OVERVIEW_KEY,)
            and ref.item_template is None
            and {COMPOSE_REPORT_TITLE_KEY, COMPOSE_OVERALL_OVERVIEW_KEY}.issubset(
                producer_fields
            )
        ):
            canonical_producer_indexes.append(prior_steps.index(producer))
    if not canonical_producer_indexes:
        return False
    referenced_step_refs = {ref.step_ref for ref in refs}
    return all(
        producer.plan_step_ref in referenced_step_refs
        for producer in prior_steps[min(canonical_producer_indexes) :]
        if producer.output_type == OutputType.JSON
        and producer.output_contract is not None
    )


def _bound_document_report_section_source(
    refs: tuple[SourceRefBinding, ...],
) -> DocumentReportSectionSource | None:
    if not refs or refs[0].item_template is None or len(refs[0].field_path) != 1:
        return None
    return DocumentReportSectionSource(
        producer_ref=refs[0].step_ref,
        field_name=refs[0].field_path[0],
    )


def _find_compose_overview_source(prior_steps: list[StepSpec]) -> StepSpec | None:
    for prior_step in reversed(prior_steps):
        properties = _schema_properties(prior_step.output_contract)
        if {COMPOSE_REPORT_TITLE_KEY, COMPOSE_OVERALL_OVERVIEW_KEY}.issubset(
            properties
        ):
            return prior_step
    return None


def _schema_properties(schema: object) -> dict[str, object]:
    if not isinstance(schema, Mapping):
        return {}
    typed_schema = cast(Mapping[str, object], schema)
    raw_properties = typed_schema.get("properties")
    if not isinstance(raw_properties, Mapping):
        return {}
    properties = cast(Mapping[object, object], raw_properties)
    return {
        key: value
        for key, value in properties.items()
        if isinstance(key, str) and isinstance(value, Mapping)
    }


def _array_item_properties(schema: object) -> dict[str, object]:
    if not isinstance(schema, Mapping):
        return {}
    typed_schema = cast(Mapping[str, object], schema)
    raw_type = typed_schema.get("type")
    if raw_type != "array":
        return {}
    return _schema_properties(typed_schema.get("items"))


def _compose_report_title_question(
    *,
    overview_step: StepSpec | None,
    ui_language: str | None,
) -> str:
    if overview_step is not None:
        return f"# {{{{ {overview_step.plan_step_ref}.output.structured.{COMPOSE_REPORT_TITLE_KEY} }}}}"
    return "# Source report" if ui_language == "en" else "# Rapport per källa"


def _compose_section_item_template(
    ui_language: str | None,
    *,
    item_properties: Mapping[str, object],
    section_label_by_key: Mapping[str, str],
) -> str:
    if not _CANONICAL_SECTION_FIELDS.issubset(item_properties):
        return _compose_source_record_item_template(
            ui_language,
            item_properties=item_properties,
            section_label_by_key=section_label_by_key,
        )
    source_label = "Source" if ui_language == "en" else "Källa"
    template = (
        f"## {{{COMPOSE_SECTION_TITLE_KEY}}}\n\n"
        f"{{{COMPOSE_SECTION_BODY_KEY}}}\n\n"
        f"{source_label}: {{{COMPOSE_SOURCE_LABEL_KEY}}}"
    )
    reserved_fields = {
        COMPOSE_SECTION_TITLE_KEY,
        COMPOSE_SECTION_BODY_KEY,
        COMPOSE_SOURCE_LABEL_KEY,
        "source_file_id",
    }
    additional_fields = [
        f"{_item_template_literal(section_label_by_key.get(field_name, _humanized_field_name(field_name)))}: "
        f"{{{field_name}}}"
        for field_name in item_properties
        if field_name not in reserved_fields
    ]
    if not additional_fields:
        return template
    return f"{template}\n\n" + "\n\n".join(additional_fields)


def _compose_source_record_item_template(
    ui_language: str | None,
    *,
    item_properties: Mapping[str, object],
    section_label_by_key: Mapping[str, str],
) -> str:
    content_fields = _source_record_content_field_names(item_properties)
    field_lines = [
        f"{_item_template_literal(section_label_by_key.get(field_name, _humanized_field_name(field_name)))}: "
        f"{{{field_name}}}"
        for field_name in content_fields
    ]
    parts = [f"## {{{COMPOSE_SOURCE_LABEL_KEY}}}"]
    if RUNTIME_SOURCE_EXTRACTION_WARNINGS_FIELD in item_properties:
        warning_label = (
            "Extraction warnings" if ui_language == "en" else "Extraktionsvarningar"
        )
        parts.append(f"{warning_label}: {{{RUNTIME_SOURCE_EXTRACTION_WARNINGS_FIELD}}}")
    if field_lines:
        parts.append("\n\n".join(field_lines))
    return "\n\n".join(parts)


def _source_record_content_field_names(
    item_properties: Mapping[str, object],
) -> tuple[str, ...]:
    return tuple(
        field_name
        for field_name in item_properties
        if field_name not in RUNTIME_MANAGED_SOURCE_FIELDS
    )


def _required_section_template_field_names(
    item_properties: Mapping[str, object],
) -> frozenset[str]:
    if _CANONICAL_SECTION_FIELDS.issubset(item_properties):
        return _CANONICAL_SECTION_FIELDS
    if COMPOSE_SOURCE_LABEL_KEY not in item_properties:
        return frozenset()
    required_fields = {
        COMPOSE_SOURCE_LABEL_KEY,
        *_source_record_content_field_names(item_properties),
    }
    if RUNTIME_SOURCE_EXTRACTION_WARNINGS_FIELD in item_properties:
        required_fields.add(RUNTIME_SOURCE_EXTRACTION_WARNINGS_FIELD)
    return frozenset(required_fields)


def _schema_declares_direct_compose_scalar(schema: object) -> bool:
    match schema:
        case {"type": str(raw_type)}:
            return raw_type in DIRECT_COMPOSE_SCALAR_FIELD_TYPES
        case {"type": [str(raw_type), "null"]}:
            return raw_type in DIRECT_COMPOSE_SCALAR_FIELD_TYPES
        case {"type": ["null", str(raw_type)]}:
            return raw_type in DIRECT_COMPOSE_SCALAR_FIELD_TYPES
        case _:
            return False


def _item_template_literal(value: str) -> str:
    return value.replace("{", "&#123;").replace("}", "&#125;")


def _compose_overview_label(ui_language: str | None) -> str:
    return "Overall overview" if ui_language == "en" else "Samlad översikt"


def _compose_field_label(field_name: str) -> str:
    return _humanized_field_name(field_name)


def _compose_additional_field_ref(
    *,
    step_ref: str,
    field_name: str,
    field_schema: object,
    label: str | None,
) -> SourceRefBinding:
    item_properties = _array_item_properties(field_schema)
    return SourceRefBinding(
        step_ref=step_ref,
        output="structured",
        field_path=(field_name,),
        label=label or _compose_field_label(field_name),
        item_template=(
            _compose_object_item_template(item_properties) if item_properties else None
        ),
    )


def _compose_object_item_template(
    item_properties: Mapping[str, object],
) -> str:
    return "\n".join(
        f"{_humanized_field_name(field_name)}: {{{field_name}}}"
        for field_name in item_properties
    )


def _humanized_field_name(field_name: str) -> str:
    return field_name.replace("_", " ").strip().capitalize()
