from __future__ import annotations

from collections import defaultdict

from intric.flows.domain.flow import Flow


def build_flow_discovery_defaults(flow: Flow | None) -> dict[str, set[str]]:
    if flow is None:
        return {}

    defaults: dict[str, set[str]] = defaultdict(set)
    steps = sorted(flow.steps, key=lambda step: step.step_order)
    if not steps:
        return {}

    first_step = steps[0]
    last_step = steps[-1]

    if first_step.input_source == "flow_input":
        if first_step.input_type in {"document", "file"}:
            defaults["input_material_mode"].add("documents")
            max_files = _runtime_input_max_files(first_step.input_config)
            if max_files is not None:
                defaults["upload_pattern"].add(
                    "multiple_pdfs" if max_files > 1 else "single_pdf"
                )
                defaults["document_material_scope"].add(
                    "multiple_documents_case"
                    if max_files > 1
                    else "single_document_case"
                )
        elif first_step.input_type == "audio":
            defaults["input_material_mode"].add("audio")

    final_output = _map_output_type(last_step.output_type)
    if final_output is not None:
        defaults["final_output_mode"].add(final_output)

    if _has_form_fields(flow):
        defaults["runtime_metadata_fields"].add("basic_case_metadata")
    elif flow.metadata_json is not None:
        defaults["runtime_metadata_fields"].add("no_extra_metadata")

    return {
        question_id: values
        for question_id, values in defaults.items()
        if values
    }


def _runtime_input_max_files(input_config: dict | None) -> int | None:
    if not isinstance(input_config, dict):
        return None
    runtime_input = input_config.get("runtime_input")
    if not isinstance(runtime_input, dict):
        return None
    max_files = runtime_input.get("max_files")
    return max_files if isinstance(max_files, int) else None


def _map_output_type(output_type: str | None) -> str | None:
    if output_type == "text":
        return "structured_text"
    if output_type == "pdf":
        return "pdf_document"
    if output_type == "docx":
        return "docx_document"
    if output_type == "json":
        return "structured_json"
    return None


def _has_form_fields(flow: Flow) -> bool:
    metadata_json = flow.metadata_json
    if not isinstance(metadata_json, dict):
        return False
    form_schema = metadata_json.get("form_schema")
    if not isinstance(form_schema, dict):
        return False
    fields = form_schema.get("fields")
    return isinstance(fields, list) and len(fields) > 0
