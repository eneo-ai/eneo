from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from flow_consumer_guide_support import (
    CONSUMER_DOCS_API_PREFIX,
    FLOW_API_GUIDE_HREF,
    RUN_STATUS_WEBHOOKS_UNSUPPORTED_CALLOUT,
    EndpointSequence,
    GuidePage,
    TestReceipt,
    UnsupportedCallout,
    endpoint_contracts_for_sequence,
    output_path_for,
    render_endpoint_sequence,
    render_json_example,
    render_markdown_table,
    render_page,
    render_unsupported_callout,
    success_status_label,
    validate_endpoint_sequences,
    validate_json_examples,
    validate_unsupported_callouts,
    write_page,
)

from eneo.files.file_models import (
    FILE_PUBLIC_EXAMPLE,
    SIGNED_URL_RESPONSE_EXAMPLE,
)
from eneo.flows.api.flow_models import (
    FLOW_RUN_CREATE_REQUEST_EXAMPLE,
    FLOW_RUN_PUBLIC_EXAMPLE,
    FLOW_RUN_QUEUED_AFTER_DISPATCH_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_APPROVE_REQUEST_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_APPROVED_RESPONSE_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_EDITED_RESPONSE_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_RESUME_REQUEST_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_RESUME_RESPONSE_EXAMPLE,
    FLOW_RUN_STEP_PUBLIC_EXAMPLE,
)
from eneo.flows.api.flow_runtime_endpoint_registry import (
    flow_runtime_endpoint_by_operation_id,
)
from eneo.flows.api.flow_runtime_paths import build_flow_endpoint_template
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_contract_models import FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE

CONSUMER_GUIDE_PAGE_SLUG = "integrating-flows"
FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH = output_path_for(CONSUMER_GUIDE_PAGE_SLUG)
CAPABILITY_MATRIX_ROWS = ()
ENDPOINT_PITFALL_ROWS = ()
SCENARIOS = ()

OPENAPI_TEST_FILE = "backend/tests/unit/test_flow_openapi_contract.py"
CONSUMER_API_TEST_FILE = (
    "backend/tests/integration/flows/test_flow_consumer_api_contract.py"
)

ExampleLanguage = Literal["json", "text"]


@dataclass(frozen=True, slots=True)
class WorkedExampleHop:
    title: str
    operation_id: str
    request_intro: str
    request_language: ExampleLanguage
    request_body: object
    response_intro: str
    response_json: object
    request_headers: tuple[tuple[str, str], ...] = ()


ENDPOINT_SEQUENCES: tuple[EndpointSequence, ...] = (
    EndpointSequence(
        slug="quickstart",
        title="Quickstart",
        summary="Discover the contract, create a run with idempotency, poll status, then read the final result.",
        steps=(
            "Call `runtime_paths.run_contract` to get required inputs, review steps, final output, and `published_flow_version`.",
            "Call `runtime_paths.create_run` with `expected_flow_version` and an `Idempotency-Key`; the response returns a run id.",
            "Call `runtime_paths.get_run_template` until the run is terminal or `awaiting_review`.",
            "Call `runtime_paths.list_steps_template` to get per-step status, output, result files, and error codes.",
        ),
        runtime_path_fields=(
            "run_contract",
            "create_run",
            "get_run_template",
            "list_steps_template",
        ),
        run_contract_fields=("published_flow_version", "final_output.delivery"),
        receipts=(
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_flow_consumer_runtime_routes_support_start_replay_poll_and_steps",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_create_flow_run_documents_idempotency_contract",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.FLOW_NOT_PUBLISHED,
            FlowApiErrorCode.RUN_IDEMPOTENCY_CONFLICT,
            FlowApiErrorCode.RUN_STALE_VERSION,
        ),
    ),
    EndpointSequence(
        slug="files",
        title="Files",
        summary="Upload files before run creation and bind returned ids to the step that consumes them.",
        steps=(
            "Call `runtime_paths.run_contract` to find `steps_requiring_input` and accepted file rules.",
            "Call `runtime_paths.upload_step_runtime_file_template` for each file; the response returns runtime file ids.",
            "Send `step_inputs[step_id].file_ids` in `runtime_paths.create_run`.",
            "Call `runtime_paths.delete_runtime_file_template` only for abandoned uploads that are not attached to a run.",
        ),
        runtime_path_fields=(
            "run_contract",
            "upload_step_runtime_file_template",
            "delete_runtime_file_template",
            "create_run",
        ),
        run_contract_fields=(
            "steps_requiring_input.step_id",
            "steps_requiring_input.max_files",
            "steps_requiring_input.accepted_mimetypes",
            "runtime_upload_policy.max_timeout_seconds",
        ),
        receipts=(
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_runtime_file_upload_multipart_schema_uses_upload_file_field",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_runtime_file_upload_error_codes_are_machine_readable",
            ),
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_flow_runtime_file_delete_rejects_attached_run_input",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.RUN_REQUIRED_STEP_INPUT_MISSING,
            FlowApiErrorCode.RUN_STEP_INPUT_MAX_FILES_EXCEEDED,
            FlowApiErrorCode.RUN_STEP_INPUT_FILE_TOO_LARGE,
            FlowApiErrorCode.RUN_STEP_INPUT_MIMETYPE_REJECTED,
            FlowApiErrorCode.RUNTIME_FILE_ATTACHED,
        ),
    ),
    EndpointSequence(
        slug="human-in-the-loop",
        title="Human-in-the-loop pause and resume",
        summary="Runs pause only at review-marked steps and resume through review checkpoint endpoints.",
        steps=(
            "Call `runtime_paths.run_contract` before run creation and inspect `steps_requiring_review`.",
            "Poll `runtime_paths.get_run_template`; when status is `awaiting_review`, show the review UI.",
            "Call `review_checkpoints.active_template` to get the open checkpoint and revision.",
            "Call `edit_template`, `approve_template`, or `reject_template`; the response returns the updated checkpoint.",
            "Call `resume_template` after approval so the worker continues the run.",
        ),
        runtime_path_fields=(
            "review_checkpoints.active_template",
            "review_checkpoints.edit_template",
            "review_checkpoints.approve_template",
            "review_checkpoints.reject_template",
            "review_checkpoints.resume_template",
            "get_run_template",
        ),
        run_contract_fields=(
            "steps_requiring_review.step_id",
            "steps_requiring_review.review_mode",
            "steps_requiring_review.expires_after_seconds",
        ),
        receipts=(
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_review_checkpoint_endpoint_docs_guide_human_in_loop_clients",
            ),
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_flow_consumer_golden_journey_uses_review_runtime_paths",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.REVIEW_STALE_REVISION,
            FlowApiErrorCode.REVIEW_EXPIRED,
            FlowApiErrorCode.REVIEW_NOT_ACTIVE,
            FlowApiErrorCode.REVIEW_IDEMPOTENCY_KEY_REQUIRED,
            FlowApiErrorCode.REVIEW_REJECT_REASON_REQUIRED,
        ),
    ),
    EndpointSequence(
        slug="mid-run-files",
        title="Sending files mid-run",
        summary="Eneo Flows does not accept arbitrary file injection while a run is executing.",
        steps=(
            "If the flow needs new files, design a review-marked step before the file-consuming step.",
            "At the checkpoint, edit the reviewed output or reject/cancel the run based on your product rules.",
            "For different runtime files, create a rerun with explicit step input overrides after the original step has completed.",
        ),
        runtime_path_fields=(
            "review_checkpoints.edit_template",
            "rerun_step_template",
        ),
        run_contract_fields=("steps_requiring_review.step_id",),
        receipts=(
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_flow_review_edit_returns_typed_contract_error_for_invalid_payload",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_run_step_rerun_contract",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.REVIEW_NOT_ACTIVE,
            FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID,
        ),
    ),
    EndpointSequence(
        slug="results",
        title="Results",
        summary="Drive the UI from run status, step results, result files, and status capabilities.",
        steps=(
            "Call `runtime_paths.get_run_template` to get run status and final output when ready.",
            "Call `runtime_paths.list_steps_template` to get each step result as it completes.",
            "Use the file id from run or step `result_files`, then call `runtime_paths.artifact_signed_url_template` to get a short-lived download URL.",
            "Call `/api/v1/flows/runs/status-capabilities/` to get status meaning instead of hardcoding transitions.",
        ),
        runtime_path_fields=(
            "get_run_template",
            "list_steps_template",
            "artifact_signed_url_template",
        ),
        endpoint_operation_ids=("get_flow_run_status_capabilities",),
        run_contract_fields=("final_output.output_type", "final_output.delivery"),
        receipts=(
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_public_run_and_step_expose_result_files",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_public_flow_failure_code_fields_are_nullable_terminal_enums",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_run_status_capabilities_guides_consumer_lifecycle",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.RUN_ARTIFACT_NOT_FOUND,
            FlowApiErrorCode.RUN_ARTIFACT_CONTENT_UNAVAILABLE,
            FlowApiErrorCode.RUN_ACCESS_DENIED,
        ),
    ),
    EndpointSequence(
        slug="reruns",
        title="Reruns",
        summary="Reruns invalidate downstream work and preserve lineage so clients can explain what changed.",
        steps=(
            "Call `runtime_paths.rerun_step_template` for a completed step to get accepted rerun operation state.",
            "Send explicit file overrides when replacing inputs; send an explicit empty override when the step should run without files.",
            "Use review checkpoint edits for corrected outputs before approval; rerun inputs are not direct post-run output edits.",
            "Poll `runtime_paths.get_run_template` and `list_steps_template`; downstream steps show the new lineage.",
        ),
        runtime_path_fields=(
            "rerun_step_template",
            "get_run_template",
            "list_steps_template",
        ),
        run_contract_fields=("steps_requiring_input.step_id",),
        receipts=(
            TestReceipt(OPENAPI_TEST_FILE, "test_openapi_flow_run_step_rerun_contract"),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_run_revision_documents_rerun_compare_token",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.RUN_RERUN_STALE_REVISION,
            FlowApiErrorCode.RUN_RERUN_INVALID_TRANSITION,
            FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND,
            FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID,
        ),
    ),
    EndpointSequence(
        slug="robustness",
        title="Robustness",
        summary="Use idempotency, version pins, cancellation, redispatch, polling backoff, and status capabilities for retry-safe clients.",
        steps=(
            "Reuse the same `Idempotency-Key` only for the same create-run payload.",
            "Send `expected_flow_version` from the run contract so edited published versions do not surprise clients.",
            "Call `runtime_paths.cancel_run_template` when the user intentionally abandons a non-terminal run.",
            "Call `runtime_paths.redispatch_run_template` only for stale queued recovery; `redispatched_count: 0` means no dispatch was needed.",
            "Back off polling when `status_capabilities.should_poll` is false.",
            "Use run and step polling as the source of truth for status changes.",
        ),
        runtime_path_fields=(
            "create_run",
            "cancel_run_template",
            "redispatch_run_template",
            "get_run_template",
        ),
        run_contract_fields=("published_flow_version",),
        receipts=(
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_create_flow_run_documents_idempotency_contract",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_run_status_capabilities_guides_consumer_lifecycle",
            ),
            TestReceipt(
                "backend/tests/unittests/flows/test_flow_run_execution_router.py",
                "test_cancel_flow_run_uses_terminalizer_audit_only",
            ),
            TestReceipt(
                "backend/tests/unittests/flows/test_flow_run_execution_router.py",
                "test_redispatch_flow_run_uses_run_scoped_dispatch_and_audits",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.RUN_IDEMPOTENCY_CONFLICT,
            FlowApiErrorCode.RUN_CONCURRENCY_LIMIT_REACHED,
            FlowApiErrorCode.RUN_USER_CANCELLED,
            FlowApiErrorCode.RUN_WORKER_STALLED,
        ),
    ),
    EndpointSequence(
        slug="failures",
        title="Failures",
        summary="Branch on typed `FlowApiErrorCode` values and show the user the specific recovery action.",
        steps=(
            "Call `runtime_paths.get_run_template` and read the run-level `error.code` when terminal failure happens.",
            "Call `runtime_paths.list_steps_template` and read the failed step and nullable step `error_code`.",
            "Map known codes to localized copy; degrade unknown codes to a generic support path.",
        ),
        runtime_path_fields=("get_run_template", "list_steps_template"),
        run_contract_fields=("final_output.output_contract",),
        receipts=(
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_run_public_exposes_structured_error",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_public_flow_failure_code_fields_are_nullable_terminal_enums",
            ),
            TestReceipt(
                OPENAPI_TEST_FILE,
                "test_openapi_flow_runtime_mutation_error_examples_match_public_codes",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.RUN_TASK_FAILURE,
            FlowApiErrorCode.STEP_EXECUTION_FAILED,
            FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
            FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED,
        ),
    ),
    EndpointSequence(
        slug="service-keys-tenancy",
        title="Service keys and tenancy guarantees",
        summary="Service keys can drive published runtime paths inside their scope and cannot inspect another principal's runs.",
        steps=(
            "Use a key scoped to the flow's space.",
            "Create runs through published runtime paths, not draft authoring paths.",
            "List runs with `runtime_paths.list_runs`; service keys see only their own runs.",
            "Request evidence only when the key has the explicit evidence permission.",
        ),
        runtime_path_fields=("create_run", "list_runs", "evidence_template"),
        run_contract_fields=("flow_id",),
        receipts=(
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_flow_service_key_can_drive_human_review_runtime_paths",
            ),
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_service_key_evidence_permission_matrix",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.RUN_ACCESS_DENIED,
            FlowApiErrorCode.RUN_EVIDENCE_FORBIDDEN,
            FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED,
        ),
    ),
)

UNSUPPORTED_CALLOUTS: tuple[UnsupportedCallout, ...] = (
    UnsupportedCallout(
        feature="Arbitrary mid-run pause",
        reason="Runs pause only at steps configured for human review.",
        supported_alternative="Design a review-marked step where your app needs human input, or rerun a completed step with explicit overrides.",
    ),
    RUN_STATUS_WEBHOOKS_UNSUPPORTED_CALLOUT,
)

ENDPOINT_SEQUENCE_INTROS: dict[str, str] = {
    "quickstart": "Start with the smallest complete run path. It proves the contract, idempotency, polling, and step-result loop.",
    "files": "When the contract names file inputs, handle uploads before you create the run.",
    "human-in-the-loop": "After inputs are bound, plan how the UI behaves when a review-marked step pauses the run.",
    "mid-run-files": "If a user asks for files during execution, route the product design through review or rerun instead of inventing an unsupported upload path.",
    "results": "Once review is resolved, drive the result screen from run status, step results, and artifact links.",
    "reruns": "When a user needs to correct completed work, use reruns so lineage and invalidation stay visible.",
    "robustness": "After the happy path works, add retries and polling rules so the integration behaves well under load.",
    "failures": "When a run or step fails, branch on typed codes and show the user the next action.",
    "service-keys-tenancy": "For backend integrations, finish by checking service-key scope and tenant isolation.",
}

FLOW_RUN_AWAITING_REVIEW_RESPONSE_EXAMPLE: dict[str, object] = {
    **FLOW_RUN_QUEUED_AFTER_DISPATCH_EXAMPLE,
    "revision": 2,
    "status": "awaiting_review",
    "dispatch_next_attempt_at": None,
    "started_at": "2026-03-17T10:05:02Z",
    "updated_at": "2026-03-17T10:05:30Z",
}

SIGNED_URL_REQUEST_EXAMPLE: dict[str, object] = {
    "expires_in": 3600,
    "content_disposition": "attachment",
}


WORKED_EXAMPLE_REVIEW_STEP = cast(
    dict[str, object],
    FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE["steps_requiring_review"][0],
)
WORKED_EXAMPLE_FINAL_OUTPUT = cast(
    dict[str, object],
    FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE["final_output"],
)
WORKED_EXAMPLE_ARTIFACT_FILE_ID = "00000000-0000-0000-0000-000000000702"
WORKED_EXAMPLE_FINAL_STEP_RESULT_ID = "00000000-0000-0000-0000-000000000504"
WORKED_EXAMPLE_TRANSCRIPTION_ORIGINAL: dict[str, object] = {
    "transcription": "Hello and welcome to the annual review..."
}
WORKED_EXAMPLE_TRANSCRIPTION_EDITED: dict[str, object] = {
    "transcription": "Corrected transcription for the annual review."
}


def _worked_checkpoint_overrides(payload: dict[str, object]) -> dict[str, object]:
    return {
        "step_id": WORKED_EXAMPLE_REVIEW_STEP["step_id"],
        "step_order": WORKED_EXAMPLE_REVIEW_STEP["step_order"],
        "original_payload_json": WORKED_EXAMPLE_TRANSCRIPTION_ORIGINAL,
        "current_payload_json": payload,
        "step_label": WORKED_EXAMPLE_REVIEW_STEP["label"],
        "review_mode": WORKED_EXAMPLE_REVIEW_STEP["review_mode"],
        "output_type": WORKED_EXAMPLE_REVIEW_STEP["output_type"],
        "output_contract": WORKED_EXAMPLE_REVIEW_STEP["output_contract"],
        "next_step_ids": [WORKED_EXAMPLE_FINAL_OUTPUT["step_id"]],
    }


WORKED_EXAMPLE_CHECKPOINT: dict[str, object] = {
    **FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE,
    **_worked_checkpoint_overrides(WORKED_EXAMPLE_TRANSCRIPTION_ORIGINAL),
}
WORKED_EXAMPLE_CHECKPOINT_EDIT_REQUEST: dict[str, object] = {
    "expected_checkpoint_revision": 1,
    "current_payload_json": WORKED_EXAMPLE_TRANSCRIPTION_EDITED,
}
WORKED_EXAMPLE_CHECKPOINT_EDITED_RESPONSE: dict[str, object] = {
    **FLOW_RUN_REVIEW_CHECKPOINT_EDITED_RESPONSE_EXAMPLE,
    **_worked_checkpoint_overrides(WORKED_EXAMPLE_TRANSCRIPTION_EDITED),
}
WORKED_EXAMPLE_CHECKPOINT_APPROVED_RESPONSE: dict[str, object] = {
    **FLOW_RUN_REVIEW_CHECKPOINT_APPROVED_RESPONSE_EXAMPLE,
    **_worked_checkpoint_overrides(WORKED_EXAMPLE_TRANSCRIPTION_EDITED),
}
WORKED_EXAMPLE_CHECKPOINT_RESUME_RESPONSE: dict[str, object] = {
    **FLOW_RUN_REVIEW_CHECKPOINT_RESUME_RESPONSE_EXAMPLE,
    "checkpoint": {
        **cast(
            dict[str, object],
            FLOW_RUN_REVIEW_CHECKPOINT_RESUME_RESPONSE_EXAMPLE["checkpoint"],
        ),
        **_worked_checkpoint_overrides(WORKED_EXAMPLE_TRANSCRIPTION_EDITED),
    },
}
WORKED_EXAMPLE_ARTIFACT_RESULT_FILE: dict[str, object] = {
    "flow_run_id": FLOW_RUN_PUBLIC_EXAMPLE["id"],
    "flow_id": FLOW_RUN_PUBLIC_EXAMPLE["flow_id"],
    "tenant_id": FLOW_RUN_PUBLIC_EXAMPLE["tenant_id"],
    "step_result_id": WORKED_EXAMPLE_FINAL_STEP_RESULT_ID,
    "step_id": WORKED_EXAMPLE_FINAL_OUTPUT["step_id"],
    "step_order": WORKED_EXAMPLE_FINAL_OUTPUT["step_order"],
    "attempt_no": 1,
    "file_id": WORKED_EXAMPLE_ARTIFACT_FILE_ID,
    "ordinal": 0,
    "source": "generated_output",
    "name": "annual-review-report.docx",
    "checksum": "sha256:annual-review-report",
    "size": 24576,
    "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "file_type": "document",
    "availability": "available",
}
WORKED_EXAMPLE_FINAL_STEP_RESULT: dict[str, object] = {
    **FLOW_RUN_STEP_PUBLIC_EXAMPLE,
    "id": WORKED_EXAMPLE_FINAL_STEP_RESULT_ID,
    "step_id": WORKED_EXAMPLE_FINAL_OUTPUT["step_id"],
    "step_order": WORKED_EXAMPLE_FINAL_OUTPUT["step_order"],
    "input_payload_json": {
        "source_step_ids": [WORKED_EXAMPLE_REVIEW_STEP["step_id"]],
    },
    "runtime_input_file_ids": [],
    "output_payload_json": None,
    "result_files": [WORKED_EXAMPLE_ARTIFACT_RESULT_FILE],
    "diagnostics": [],
}
WORKED_EXAMPLE_SIGNED_URL_RESPONSE: dict[str, object] = {
    **SIGNED_URL_RESPONSE_EXAMPLE,
    "url": (
        "https://api.example.com/api/v1/files/"
        f"{WORKED_EXAMPLE_ARTIFACT_FILE_ID}/download/?token=signed-token"
    ),
}


WORKED_EXAMPLE_HOPS: tuple[WorkedExampleHop, ...] = (
    WorkedExampleHop(
        title="Discover contract",
        operation_id="get_flow_run_contract",
        request_intro="Request the published run contract before you show upload or form controls.",
        request_language="text",
        request_body="GET /api/v1/flows/{id}/run-contract/",
        response_intro="The response tells your app which inputs, review steps, and final output to expect.",
        response_json=FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE,
    ),
    WorkedExampleHop(
        title="Upload runtime file",
        operation_id="upload_flow_runtime_file",
        request_intro="Upload the audio file to the step that consumes audio input.",
        request_language="text",
        request_body=(
            "POST /api/v1/flows/{id}/steps/{step_id}/runtime-files/\n"
            "Content-Type: multipart/form-data\n\n"
            "upload_file=@review-audio.mp3"
        ),
        response_intro="The response returns the file id that will be bound to the step input.",
        response_json=FILE_PUBLIC_EXAMPLE,
    ),
    WorkedExampleHop(
        title="Create run",
        operation_id="create_flow_run",
        request_intro="Create the run with the version pin and the uploaded file bound to the audio step.",
        request_language="json",
        request_body=FLOW_RUN_CREATE_REQUEST_EXAMPLE,
        response_intro="The response gives your app the run id to poll.",
        response_json=FLOW_RUN_PUBLIC_EXAMPLE,
        request_headers=(("Idempotency-Key", "audio-report-alex-example-2026-03-17"),),
    ),
    WorkedExampleHop(
        title="Poll run",
        operation_id="get_flow_run",
        request_intro="Poll the run until it is terminal or reaches `awaiting_review`.",
        request_language="text",
        request_body="GET /api/v1/flows/{id}/runs/{run_id}/",
        response_intro="When review is needed, the run status tells the UI to open the review flow.",
        response_json=FLOW_RUN_AWAITING_REVIEW_RESPONSE_EXAMPLE,
    ),
    WorkedExampleHop(
        title="Find active review",
        operation_id="get_active_flow_run_review_checkpoint",
        request_intro="Fetch the active checkpoint before showing the review screen.",
        request_language="text",
        request_body="GET /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
        response_intro="The response includes the checkpoint id, current payload, and revision.",
        response_json=WORKED_EXAMPLE_CHECKPOINT,
    ),
    WorkedExampleHop(
        title="Edit review payload",
        operation_id="edit_flow_run_review_checkpoint",
        request_intro="Submit the full corrected payload with the revision the reviewer saw.",
        request_language="json",
        request_body=WORKED_EXAMPLE_CHECKPOINT_EDIT_REQUEST,
        response_intro="The response returns the edited checkpoint and the next revision.",
        response_json=WORKED_EXAMPLE_CHECKPOINT_EDITED_RESPONSE,
    ),
    WorkedExampleHop(
        title="Approve review",
        operation_id="approve_flow_run_review_checkpoint",
        request_intro="Approve the edited checkpoint with the latest revision.",
        request_language="json",
        request_body=FLOW_RUN_REVIEW_CHECKPOINT_APPROVE_REQUEST_EXAMPLE,
        response_intro="The response records the approval and gives the revision used for resume.",
        response_json=WORKED_EXAMPLE_CHECKPOINT_APPROVED_RESPONSE,
    ),
    WorkedExampleHop(
        title="Resume run",
        operation_id="resume_flow_run_review_checkpoint",
        request_intro="Resume the run after approval so the worker can continue.",
        request_language="json",
        request_body=FLOW_RUN_REVIEW_CHECKPOINT_RESUME_REQUEST_EXAMPLE,
        response_intro="The response returns the resumed checkpoint and the queued run.",
        response_json=WORKED_EXAMPLE_CHECKPOINT_RESUME_RESPONSE,
        request_headers=(
            (
                "Idempotency-Key",
                f"review-resume-{WORKED_EXAMPLE_CHECKPOINT['id']}",
            ),
        ),
    ),
    WorkedExampleHop(
        title="List and filter step output",
        operation_id="list_flow_run_steps",
        request_intro="There is no single-step GET for run steps. Call the list endpoint and filter the list by `step_id` for the final DOCX step.",
        request_language="text",
        request_body="GET /api/v1/flows/{id}/runs/{run_id}/steps/",
        response_intro="The full response normally contains every step; this example shows the final artifact-producing step after filtering.",
        response_json=[WORKED_EXAMPLE_FINAL_STEP_RESULT],
    ),
    WorkedExampleHop(
        title="Fetch final artifact",
        operation_id="generate_flow_run_artifact_signed_url",
        request_intro="Request a short-lived signed URL for the artifact file id from the final step result.",
        request_language="json",
        request_body=SIGNED_URL_REQUEST_EXAMPLE,
        response_intro="The response contains the download URL and an epoch-integer `expires_at` value.",
        response_json=WORKED_EXAMPLE_SIGNED_URL_RESPONSE,
    ),
)


def validate_flow_consumer_guide_catalog() -> None:
    validate_endpoint_sequences(ENDPOINT_SEQUENCES)
    validate_unsupported_callouts(UNSUPPORTED_CALLOUTS)
    validate_worked_example_hops(WORKED_EXAMPLE_HOPS)
    sequence_slugs = {sequence.slug for sequence in ENDPOINT_SEQUENCES}
    intro_slugs = set(ENDPOINT_SEQUENCE_INTROS)
    if intro_slugs != sequence_slugs:
        raise ValueError(
            "Endpoint sequence intros must match endpoint sequences: "
            f"missing={sorted(sequence_slugs - intro_slugs)}; "
            f"stale={sorted(intro_slugs - sequence_slugs)}"
        )
    for slug, intro in ENDPOINT_SEQUENCE_INTROS.items():
        _require_worked_example_text(intro, f"{slug} endpoint sequence intro")


def validate_worked_example_hops(hops: tuple[WorkedExampleHop, ...]) -> None:
    endpoint_by_operation_id = flow_runtime_endpoint_by_operation_id()
    if not hops:
        raise ValueError("Worked example must define hops")
    for hop in hops:
        if hop.operation_id not in endpoint_by_operation_id:
            raise ValueError(
                f"Worked example uses unknown operation id: {hop.operation_id}"
            )
        _require_worked_example_text(hop.title, f"{hop.operation_id} title")
        _require_worked_example_text(
            hop.request_intro,
            f"{hop.operation_id} request intro",
        )
        _require_worked_example_text(
            hop.response_intro,
            f"{hop.operation_id} response intro",
        )
        if hop.request_language == "json":
            validate_json_examples((render_json_example(hop.request_body),))
        validate_json_examples((render_json_example(hop.response_json),))


def render_worked_example() -> str:
    validate_worked_example_hops(WORKED_EXAMPLE_HOPS)
    lines = [
        "## Worked end-to-end example",
        "",
        "This example follows an audio-to-report run from contract discovery to final artifact download.",
        "",
        "Each response below is a public example for that hop. Use it to understand shape and order; your ids and timestamps will differ.",
        "",
        "Endpoint order:",
        "",
        _render_worked_example_endpoint_table(),
        "",
        *(
            section
            for index, hop in enumerate(WORKED_EXAMPLE_HOPS, start=1)
            for section in (_render_worked_example_hop(index, hop), "")
        ),
    ]
    return "\n".join(lines).rstrip()


def render_sequence_overview() -> str:
    validate_endpoint_sequences(ENDPOINT_SEQUENCES)
    rows: list[tuple[str, ...]] = []
    for sequence in ENDPOINT_SEQUENCES:
        entry_contract = endpoint_contracts_for_sequence(sequence)[0]
        rows.append(
            (
                sequence.title,
                sequence.summary,
                (
                    f"`{entry_contract.method.upper()} "
                    f"{build_flow_endpoint_template(entry_contract.route_path, api_prefix=CONSUMER_DOCS_API_PREFIX)}` "
                    f"(`{entry_contract.operation_id}`)"
                ),
            )
        )

    return "\n".join(
        (
            "## Sequence overview",
            "",
            "Use this table to choose the right runtime journey before you read the detailed endpoint facts below.",
            "",
            render_markdown_table(
                ("Journey", "Use it when", "Key endpoint"), tuple(rows)
            ),
        )
    )


def _render_worked_example_endpoint_table() -> str:
    endpoint_by_operation_id = flow_runtime_endpoint_by_operation_id()
    return render_markdown_table(
        ("Hop", "Endpoint", "Method", "Success", "Operation"),
        tuple(
            (
                hop.title,
                f"`{build_flow_endpoint_template(endpoint_by_operation_id[hop.operation_id].route_path, api_prefix=CONSUMER_DOCS_API_PREFIX)}`",
                f"`{endpoint_by_operation_id[hop.operation_id].method.upper()}`",
                f"`{success_status_label(endpoint_by_operation_id[hop.operation_id].success_status)}`",
                f"`{hop.operation_id}`",
            )
            for hop in WORKED_EXAMPLE_HOPS
        ),
    )


def _render_worked_example_hop(index: int, hop: WorkedExampleHop) -> str:
    request_block = _render_worked_example_request_block(hop)
    response_block = "\n".join(
        (
            "Response:",
            "",
            "```json",
            render_json_example(hop.response_json),
            "```",
        )
    )
    return "\n".join(
        (
            f"### {index}. {hop.title}",
            "",
            hop.request_intro,
            "",
            request_block,
            "",
            hop.response_intro,
            "",
            response_block,
        )
    )


def _render_worked_example_request_block(hop: WorkedExampleHop) -> str:
    header_block = _render_worked_example_request_headers(hop)
    if hop.request_language == "json":
        lines = ["Request:"]
        if header_block:
            lines.extend(("", header_block, "", "Body:"))
        lines.extend(("", "```json", render_json_example(hop.request_body), "```"))
        return "\n".join(lines)
    lines = ["Request:"]
    if header_block:
        lines.extend(("", header_block))
    lines.extend(("", "```text", str(hop.request_body), "```"))
    return "\n".join(lines)


def _render_worked_example_request_headers(hop: WorkedExampleHop) -> str | None:
    if not hop.request_headers:
        return None
    return "\n".join(
        (
            "Headers:",
            "",
            "```text",
            *(f"{name}: {value}" for name, value in hop.request_headers),
            "```",
        )
    )


def _require_worked_example_text(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    if "\n" in value or len(value) > 360:
        raise ValueError(f"{label} must be one short sentence")
    if "|" in value:
        raise ValueError(f"{label} must not contain table pipes")


def render_flow_consumer_guide_page() -> str:
    validate_flow_consumer_guide_catalog()
    body = (
        f"Use this page for flow runtime journeys. Use the reference for full schemas: [Flows API Guide]({FLOW_API_GUIDE_HREF}).",
        "",
        render_sequence_overview(),
        "",
        render_worked_example(),
        "",
        "## Endpoint sequences",
        "",
        *(
            section
            for sequence in ENDPOINT_SEQUENCES
            for section in (
                ENDPOINT_SEQUENCE_INTROS[sequence.slug],
                "",
                render_endpoint_sequence(sequence),
                "",
            )
        ),
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[0]),
        "",
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[1]),
    )
    return render_page(
        GuidePage(
            slug=CONSUMER_GUIDE_PAGE_SLUG,
            title="Integrating Flows",
            purpose="This page is for teams wiring Eneo Flows into an application, and it shows the endpoint order for creating, reviewing, rerunning, and finishing a run.",
            orientation="You are in the integration step of the consumer journey, where the published design becomes runtime calls and user-facing states.",
            body=body,
        )
    )


def write_flow_consumer_guide_page() -> None:
    write_page(FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH, render_flow_consumer_guide_page())


if __name__ == "__main__":
    write_flow_consumer_guide_page()
