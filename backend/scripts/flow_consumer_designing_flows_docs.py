from __future__ import annotations

from flow_consumer_guide_support import (
    CAPABILITY_MATRIX_ROW_BUDGET,
    FLOW_API_GUIDE_HREF,
    IMAGE_INPUT_UNSUPPORTED_CALLOUT,
    CapabilityMatrixRow,
    EndpointSequence,
    GuideCallout,
    GuidePage,
    Scenario,
    ScenarioStep,
    TestReceipt,
    UnsupportedCallout,
    output_path_for,
    render_callout,
    render_endpoint_sequence,
    render_markdown_table,
    render_page,
    render_scenario,
    render_unsupported_callout,
    validate_capability_matrix,
    validate_endpoint_sequences,
    validate_guide_callouts,
    validate_scenarios,
    validate_unsupported_callouts,
    write_page,
)

from intric.flows.enums import FlowOutputMode, FlowOutputType
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_capability_manifest import FINAL_OUTPUT_ARTIFACT_BY_TYPE

CONSUMER_GUIDE_PAGE_SLUG = "designing-flows"
FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH = output_path_for(CONSUMER_GUIDE_PAGE_SLUG)

CAPABILITY_MATRIX_ROWS: tuple[CapabilityMatrixRow, ...] = (
    CapabilityMatrixRow(
        input_mode="text",
        output_artifact=FINAL_OUTPUT_ARTIFACT_BY_TYPE[FlowOutputType.TEXT],
        output_types=(FlowOutputType.TEXT.value,),
        output_modes=(FlowOutputMode.PASS_THROUGH.value,),
        notes="Use for form fields, pasted text, and final text answers.",
    ),
    CapabilityMatrixRow(
        input_mode="text",
        output_artifact=FINAL_OUTPUT_ARTIFACT_BY_TYPE[FlowOutputType.JSON],
        output_types=(FlowOutputType.JSON.value,),
        output_modes=(FlowOutputMode.PASS_THROUGH.value,),
        notes="Use when later steps or your app need structured fields.",
    ),
    CapabilityMatrixRow(
        input_mode="documents",
        output_artifact=FINAL_OUTPUT_ARTIFACT_BY_TYPE[FlowOutputType.TEXT],
        output_types=(FlowOutputType.TEXT.value,),
        output_modes=(FlowOutputMode.PASS_THROUGH.value,),
        notes="Use for summaries, analyses, and human-readable reports.",
    ),
    CapabilityMatrixRow(
        input_mode="documents",
        output_artifact=FINAL_OUTPUT_ARTIFACT_BY_TYPE[FlowOutputType.JSON],
        output_types=(FlowOutputType.JSON.value,),
        output_modes=(FlowOutputMode.PASS_THROUGH.value,),
        notes="Use for extraction before comparison, review, or artifacts.",
    ),
    CapabilityMatrixRow(
        input_mode="documents",
        output_artifact=FINAL_OUTPUT_ARTIFACT_BY_TYPE[FlowOutputType.PDF],
        output_types=(FlowOutputType.PDF.value,),
        output_modes=(FlowOutputMode.PASS_THROUGH.value,),
        notes="Use when the final result should be a generated PDF artifact.",
    ),
    CapabilityMatrixRow(
        input_mode="documents",
        output_artifact=FINAL_OUTPUT_ARTIFACT_BY_TYPE[FlowOutputType.DOCX],
        output_types=(FlowOutputType.DOCX.value,),
        output_modes=(
            FlowOutputMode.PASS_THROUGH.value,
            FlowOutputMode.TEMPLATE_FILL.value,
        ),
        notes="Use generated DOCX for free-form documents and template fill for fixed templates.",
    ),
    CapabilityMatrixRow(
        input_mode="audio",
        output_artifact=FINAL_OUTPUT_ARTIFACT_BY_TYPE[FlowOutputType.TEXT],
        output_types=(FlowOutputType.TEXT.value,),
        output_modes=(FlowOutputMode.TRANSCRIBE_ONLY.value,),
        notes="Use for transcription before later text, JSON, or artifact steps.",
    ),
)
ENDPOINT_PITFALL_ROWS = ()
WORKED_EXAMPLE_HOPS = ()

ENDPOINT_SEQUENCES: tuple[EndpointSequence, ...] = (
    EndpointSequence(
        slug="discover-design-contract",
        title="Design from the published contract",
        summary="Before building a UI, inspect the runtime paths and run contract for the published flow version.",
        steps=(
            "Call `GET /api/v1/flows/{id}/published/` to get runtime-safe paths for service-key or user clients.",
            "Call `GET runtime_paths.run_contract` to get required form fields, file inputs, review steps, and final output.",
            "Call `GET runtime_paths.graph` to get the published topology your app can show before a run.",
            "Use `published_flow_version` as the version pin when your app creates a run.",
        ),
        runtime_path_fields=("run_contract", "graph"),
        endpoint_operation_ids=("get_published_flow_runtime",),
        run_contract_fields=(
            "published_flow_version",
            "form_fields.name",
            "steps_requiring_input.step_id",
            "steps_requiring_review.review_mode",
            "final_output.delivery",
        ),
        receipts=(
            TestReceipt(
                "backend/tests/unit/test_flow_openapi_contract.py",
                "test_openapi_run_contract_guides_consumer_forms_uploads_and_review",
            ),
            TestReceipt(
                "backend/tests/unit/test_flow_openapi_contract.py",
                "test_openapi_runtime_paths_expose_review_checkpoint_templates",
            ),
            TestReceipt(
                "backend/tests/unittests/flows/test_flow_router_crud.py",
                "test_get_published_flow_runtime_returns_runtime_projection_for_human_reader",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.FLOW_NOT_PUBLISHED,
            FlowApiErrorCode.FLOW_DELETED,
            FlowApiErrorCode.RUN_STALE_VERSION,
        ),
    ),
)

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        slug="speech-to-structured-report",
        title="Speech to structured report",
        goal="Turn an audio upload into structured sections and a filled DOCX template.",
        design_rows=(
            ScenarioStep(
                "Transcribe audio",
                "Runtime audio upload",
                "Text transcript",
                "`step_inputs[transcribe].file_ids`",
                "None",
            ),
            ScenarioStep(
                "Extract sections",
                "Transcript text",
                "JSON section headers",
                "`{{step_a.output.text}}`",
                "None",
            ),
            ScenarioStep(
                "Compose report",
                "Section JSON",
                "Report text",
                "`{{step_b.output.structured.sections}}`",
                "Step knowledge",
            ),
            ScenarioStep(
                "Fill template",
                "Report text",
                "DOCX artifact (`template_fill`)",
                "`{{step_c.output.text}}`",
                "Template asset",
            ),
        ),
        why_this_shape="The flow keeps speech, structure, prose, and template rendering in separate steps so each failure is visible and rerunnable.",
        golden_ids=("audio_to_docx_template__advanced",),
    ),
    Scenario(
        slug="document-intake-with-human-gate",
        title="Document intake with human gate",
        goal="Extract uploaded documents, pause for review, and produce a final artifact.",
        design_rows=(
            ScenarioStep(
                "Extract upload",
                "Runtime document upload",
                "JSON fields",
                "`step_inputs[extract].file_ids`",
                "None",
            ),
            ScenarioStep(
                "Review fields",
                "Extracted JSON",
                "Approved or edited JSON",
                "Review checkpoint",
                "Reviewer judgment",
            ),
            ScenarioStep(
                "Create artifact",
                "Approved JSON",
                "DOCX artifact",
                "`{{reviewed_fields}}`",
                "Template asset",
            ),
        ),
        why_this_shape="The review checkpoint freezes the extracted fields before the artifact step consumes them.",
        golden_ids=("document_to_docx_template__advanced",),
        receipts=(
            TestReceipt(
                "backend/tests/integration/flows/test_flow_consumer_api_contract.py",
                "test_flow_consumer_golden_journey_uses_review_runtime_paths",
            ),
        ),
    ),
    Scenario(
        slug="compare-and-decide",
        title="Compare and decide",
        goal="Compare two uploads against caller-supplied criteria and return a recommendation.",
        design_rows=(
            ScenarioStep(
                "Read first upload",
                "Runtime document upload",
                "JSON metrics",
                "`step_inputs[first].file_ids`",
                "None",
            ),
            ScenarioStep(
                "Read second upload",
                "Runtime document upload",
                "JSON metrics",
                "`step_inputs[second].file_ids`",
                "None",
            ),
            ScenarioStep(
                "Recommend",
                "Both JSON outputs plus criteria",
                "Text recommendation",
                "`ALL_PREVIOUS_STEPS` and form field",
                "None",
            ),
        ),
        why_this_shape="The comparison step receives both structured extractions and a clear weighting field instead of prose-only chaining.",
        golden_ids=("comparison__advanced",),
    ),
    Scenario(
        slug="form-intake-to-artifact",
        title="Form intake to artifact",
        goal="Use form fields to compose sections and generate a DOCX artifact.",
        design_rows=(
            ScenarioStep(
                "Collect sections",
                "Runtime form fields",
                "Draft text",
                "`input_payload_json`",
                "None",
            ),
            ScenarioStep(
                "Compose artifact body",
                "Draft text",
                "Final text",
                "`{{step_a.output.text}}`",
                "Optional step knowledge",
            ),
            ScenarioStep(
                "Fill template",
                "Final text",
                "DOCX artifact",
                "`{{step_b.output.text}}`",
                "Template asset",
            ),
        ),
        why_this_shape="The form-only path avoids fake uploads and makes every caller-provided value explicit in the run payload.",
        golden_ids=("form_intake_to_docx_template__advanced",),
    ),
)

UNSUPPORTED_CALLOUTS: tuple[UnsupportedCallout, ...] = (
    IMAGE_INPUT_UNSUPPORTED_CALLOUT,
)

ANTI_PATTERN_CALLOUTS: tuple[GuideCallout, ...] = (
    GuideCallout(
        title="Anti-pattern: One giant step",
        body=(
            "One broad instruction hides which part failed and makes review harder.",
            "Better design: split extraction, reasoning, review, and artifact rendering into separate steps.",
        ),
    ),
)


def validate_flow_consumer_guide_catalog() -> None:
    validate_capability_matrix(CAPABILITY_MATRIX_ROWS, CAPABILITY_MATRIX_ROW_BUDGET)
    validate_endpoint_sequences(ENDPOINT_SEQUENCES)
    validate_scenarios(SCENARIOS)
    validate_unsupported_callouts(UNSUPPORTED_CALLOUTS)
    validate_guide_callouts(ANTI_PATTERN_CALLOUTS)


def render_flow_consumer_guide_page() -> str:
    validate_flow_consumer_guide_catalog()
    matrix_rows = tuple(
        (
            row.input_mode,
            row.output_artifact,
            ", ".join(row.output_types),
            ", ".join(row.output_modes),
            row.notes,
        )
        for row in CAPABILITY_MATRIX_ROWS
    )
    body = (
        f"The reference guide keeps the full field catalog: [Flows API Guide]({FLOW_API_GUIDE_HREF}).",
        "",
        "## Building blocks",
        "",
        "A Flow is a published graph of steps. Each step declares `input_source`, `input_type`, `output_type`, and `output_mode`.",
        "",
        render_markdown_table(
            (
                "Input mode",
                "Output artifact",
                "Output types",
                "Output modes",
                "Use it when",
            ),
            matrix_rows,
        ),
        "",
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[0]),
        "",
        "## Inputs done right",
        "",
        "Use runtime uploads for files, form fields for caller choices, and pasted text for small text inputs.",
        "",
        "Reserved `input_payload_json` keys stay owned by the backend; do not create form fields with reserved names.",
        "",
        "```json",
        json_payload_example(),
        "```",
        "",
        render_endpoint_sequence(ENDPOINT_SEQUENCES[0]),
        "",
        "## Chaining steps",
        "",
        "Prefer targeted references such as `{{step_a.output.structured.fields}}` over broad all-previous-step prose.",
        "",
        "Use JSON steps when another step or your app needs stable fields. Use text steps for human-facing prose.",
        "",
        "## Knowledge, models, and artifacts",
        "",
        "Attach knowledge only to the step that needs it. Different steps may use different model choices when the published Flow exposes that design.",
        "",
        "Use DOCX template fill for fixed placeholders, DOCX create for generated documents, and PDF when the result is a final read-only artifact.",
        "",
        "## Review design",
        "",
        "Mark the step that needs human judgment for review. The run pauses at that step; arbitrary mid-run pause is not the supported model.",
        "",
        "## Anti-patterns",
        "",
        render_callout(ANTI_PATTERN_CALLOUTS[0]),
        "",
        "Avoid chaining only through prose when a JSON contract would give your app stable fields.",
        "",
        "Avoid baking runtime data into instructions. Put caller data in form fields or runtime file bindings.",
        "",
        "## Worked scenarios",
        "",
        *(
            section
            for scenario in SCENARIOS
            for section in (render_scenario(scenario), "")
        ),
    )
    return render_page(
        GuidePage(
            slug=CONSUMER_GUIDE_PAGE_SLUG,
            title="Designing Flows",
            purpose="This page is for teams shaping a published Eneo Flow before integration work begins, and it helps you choose supported steps, inputs, review points, and artifact outputs.",
            orientation="You are in the design step of the consumer journey, where the flow shape is settled before the runtime endpoints are wired.",
            body=body,
        )
    )


def json_payload_example() -> str:
    return """{
  "input_payload_json": {
    "case_type": "intake",
    "priority": "normal"
  },
  "step_inputs": {
    "STEP_ID": {
      "file_ids": ["RUNTIME_FILE_ID"]
    }
  }
}"""


def write_flow_consumer_guide_page() -> None:
    write_page(FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH, render_flow_consumer_guide_page())


if __name__ == "__main__":
    write_flow_consumer_guide_page()
