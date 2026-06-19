from __future__ import annotations

from flow_consumer_guide_support import (
    FLOW_API_GUIDE_HREF,
    FLOW_CONSUMER_GUIDES_HREF,
    IMAGE_INPUT_UNSUPPORTED_CALLOUT,
    RUN_STATUS_WEBHOOKS_UNSUPPORTED_CALLOUT,
    EndpointPitfallRow,
    EndpointSequence,
    GuidePage,
    TestReceipt,
    UnsupportedCallout,
    async_accepted_operation_ids,
    output_path_for,
    render_endpoint_pitfall_matrix,
    render_endpoint_sequence,
    render_page,
    render_unsupported_callout,
    validate_endpoint_pitfall_rows,
    validate_endpoint_sequences,
    validate_unsupported_callouts,
    write_page,
)

from intric.flows.flow_api_error_code import FlowApiErrorCode

CONSUMER_GUIDE_PAGE_SLUG = "flows-faq"
FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH = output_path_for(CONSUMER_GUIDE_PAGE_SLUG)
CAPABILITY_MATRIX_ROWS = ()
SCENARIOS = ()

OPENAPI_TEST_FILE = "backend/tests/unit/test_flow_openapi_contract.py"

ENDPOINT_PITFALL_ROWS: tuple[EndpointPitfallRow, ...] = (
    EndpointPitfallRow(
        category="idempotency",
        capability="Start a run safely",
        operation_ids=("create_flow_run",),
        pitfall="Reusing a retry key with different input returns a conflict.",
        error_code=FlowApiErrorCode.RUN_IDEMPOTENCY_CONFLICT,
    ),
    EndpointPitfallRow(
        category="polling",
        capability="Poll without hammering",
        operation_ids=(
            "get_flow_run_status_capabilities",
            "get_flow_run",
            "list_flow_run_steps",
        ),
        pitfall="Status capabilities tell you when polling should slow down or stop.",
        consumer_action="Use status capabilities for cadence and poll run or step endpoints only while progress can change.",
    ),
    EndpointPitfallRow(
        category="async_accepted",
        capability="Continue after review or rerun",
        operation_ids=async_accepted_operation_ids(),
        pitfall="`202 Accepted` means work was queued, not finished.",
        consumer_action="Poll the run and step list for completion before showing final output.",
    ),
    EndpointPitfallRow(
        category="artifact_retention",
        capability="Open retained artifacts or evidence",
        operation_ids=(
            "generate_flow_run_artifact_signed_url",
            "get_flow_run_evidence",
            "export_flow_run_evidence",
        ),
        pitfall="Purged content can leave metadata but no downloadable file content.",
        error_code=FlowApiErrorCode.RUN_ARTIFACT_CONTENT_UNAVAILABLE,
    ),
    EndpointPitfallRow(
        category="outbound_delivery_failure",
        capability="Handle outbound delivery failure",
        operation_ids=(
            "get_flow_run",
            "list_flow_run_steps",
            "generate_flow_run_artifact_signed_url",
        ),
        pitfall="The run can finish but final outbound delivery can be dead-lettered.",
        error_code=FlowApiErrorCode.WEBHOOK_DELIVERY_FAILED,
    ),
)

ENDPOINT_SEQUENCES: tuple[EndpointSequence, ...] = (
    EndpointSequence(
        slug="test-integration",
        title="Testing your integration",
        summary="Use the published contract and OpenAPI error examples as the smoke-test source.",
        steps=(
            "Call `runtime_paths.run_contract` in test setup and assert your UI can render every required input.",
            "Create a run with a deterministic `Idempotency-Key` and assert replay returns the same run.",
            "Poll run and step endpoints and assert your UI branches on known `FlowApiErrorCode` values.",
        ),
        runtime_path_fields=(
            "run_contract",
            "create_run",
            "get_run_template",
            "list_steps_template",
        ),
        run_contract_fields=("form_fields.name", "steps_requiring_input.step_id"),
        receipts=(
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_consumer_request_response_schemas",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_consumer_error_contracts",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.RUN_IDEMPOTENCY_CONFLICT,
            FlowApiErrorCode.RUN_INVALID_STEP_INPUTS,
            FlowApiErrorCode.RUN_ACCESS_DENIED,
        ),
    ),
)

UNSUPPORTED_CALLOUTS: tuple[UnsupportedCallout, ...] = (
    UnsupportedCallout(
        feature="AI Builder-authored HTTP steps",
        reason="Published flows can deliver final output through outbound HTTP; delivery failures surface as flow_webhook_delivery_failed. AI Builder cannot author HTTP steps today.",
        supported_alternative="Configure supported published-flow outputs and use your app or backend to call external APIs around the run.",
    ),
    IMAGE_INPUT_UNSUPPORTED_CALLOUT,
    RUN_STATUS_WEBHOOKS_UNSUPPORTED_CALLOUT,
    UnsupportedCallout(
        feature="Live audio streaming",
        reason="Runtime uploads accept completed files, not live browser audio chunks.",
        supported_alternative="Upload the completed audio file, then start the run with a stable idempotency key.",
    ),
)


def validate_flow_consumer_guide_catalog() -> None:
    validate_endpoint_sequences(ENDPOINT_SEQUENCES)
    validate_endpoint_pitfall_rows(ENDPOINT_PITFALL_ROWS)
    validate_unsupported_callouts(UNSUPPORTED_CALLOUTS)


def render_flow_consumer_guide_page() -> str:
    validate_flow_consumer_guide_catalog()
    body = (
        f"Use this FAQ for quick capability and operations answers. Use the reference for schemas: [Flows API Guide]({FLOW_API_GUIDE_HREF}).",
        "",
        "## What can flows do?",
        "",
        "- Accept text, JSON, document, file, and audio runtime inputs that the published run contract exposes.",
        "- Produce text, JSON, PDF, and DOCX final outputs.",
        "- Use different step designs for extraction, comparison, review, and artifact generation.",
        "- Use step-specific knowledge when the published Flow includes it.",
        "- Be edited after publish; consumers should pin `expected_flow_version` when creating runs.",
        "",
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[0]),
        "",
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[1]),
        "",
        "## Can I build this case?",
        "",
        f"- Speech to structured report: yes. See [Designing Flows]({FLOW_CONSUMER_GUIDES_HREF}/designing-flows#speech-to-structured-report).",
        f"- Document intake with human gate: yes. See [Designing Flows]({FLOW_CONSUMER_GUIDES_HREF}/designing-flows#document-intake-with-human-gate).",
        f"- Compare and decide: yes. See [Designing Flows]({FLOW_CONSUMER_GUIDES_HREF}/designing-flows#compare-and-decide).",
        f"- Form intake to artifact: yes. See [Designing Flows]({FLOW_CONSUMER_GUIDES_HREF}/designing-flows#form-intake-to-artifact).",
        "",
        "## Capability and endpoint pitfalls",
        "",
        render_endpoint_pitfall_matrix(ENDPOINT_PITFALL_ROWS),
        "",
        "## Operations",
        "",
        "- Pause and resume: runs pause at review-marked steps; arbitrary mid-run pause is not supported.",
        "- Mid-run files: use review design or rerun overrides; do not inject files into an executing step.",
        "- Results: read per-step results as they complete and use final output for the terminal answer.",
        "",
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[2]),
        "",
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[3]),
        "",
        render_endpoint_sequence(ENDPOINT_SEQUENCES[0]),
    )
    return render_page(
        GuidePage(
            slug=CONSUMER_GUIDE_PAGE_SLUG,
            title="Flows FAQ",
            purpose="This page is for teams that need a short answer about Eneo Flows capability or operations before they open the full API reference.",
            orientation="You are near the end of the consumer journey, where common design, run, review, file, and failure questions are answered in one place.",
            body=body,
        )
    )


def write_flow_consumer_guide_page() -> None:
    write_page(FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH, render_flow_consumer_guide_page())


if __name__ == "__main__":
    write_flow_consumer_guide_page()
