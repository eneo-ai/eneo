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
from eneo.flows.api.flow_run_contract_models import FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE
from eneo.flows.api.flow_runtime_endpoint_registry import (
    flow_runtime_endpoint_by_operation_id,
)
from eneo.flows.api.flow_runtime_paths import build_flow_endpoint_template
from eneo.flows.enums import FLOW_RUN_STATUS_CAPABILITIES, FlowRunStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRY_MAX_SECONDS,
    FLOW_REVIEW_EXPIRY_MIN_SECONDS,
    FLOW_REVIEW_EXPIRY_RECONCILE_INTERVAL_SECONDS,
)

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
        slug="evidence",
        title="Evidence and provider usage",
        summary="Inspect run evidence, page every provider-call lifecycle row, and export a verified evidence bundle.",
        steps=(
            "Call `runtime_paths.evidence_template` for the redacted run trace and its first bounded `provider_calls` page.",
            "Call `runtime_paths.provider_calls_template` with `after_event_id` until `has_more` is false when the UI needs every provider call.",
            "Treat `outcome_unknown` as possible remote work or spend; never infer a safe retry from missing terminal evidence.",
            "Call `runtime_paths.export_evidence_template` for a hashed support or compliance bundle; use paginated provider-call evidence when the synchronous export limit is exceeded.",
        ),
        runtime_path_fields=(
            "evidence_template",
            "provider_calls_template",
            "export_evidence_template",
        ),
        run_contract_fields=(),
        receipts=(
            TestReceipt(
                "backend/tests/integration/flows/test_flow_evidence_api_contracts.py",
                "test_provider_call_evidence_endpoint_pages_relational_lifecycle_events",
            ),
            TestReceipt(
                "backend/tests/unittests/flows/test_flow_run_evidence_service.py",
                "test_export_rejects_more_than_provider_call_safety_boundary",
            ),
        ),
        error_codes=(
            FlowApiErrorCode.PROVIDER_CALL_EVIDENCE_PERSISTENCE_FAILED,
            FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE,
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
            "Read checkpoint `schema_version`; treat an unsupported version as non-editable and refresh or upgrade the client.",
            "For edit review, send the full payload with canonical string `text`; keep it within the ordinary inline UTF-8 limit and validate `structured` against `output_contract`.",
            "Preserve runtime-owned payload keys unchanged. Never create or change `text_overflow`; an existing value is accepted only while its generated-output file belongs to the same run, step, and attempt.",
            "Offer edit review only for editable text or structured outputs. PDF and DOCX artifact steps support view review, not edit review.",
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
        summary="Drive the UI from the typed final result, step details, artifact links, and status capabilities.",
        steps=(
            "Call `runtime_paths.get_run_template` and switch exhaustively on `result.kind` after the run completes; `result` is null before a successful terminal result exists.",
            "Treat `structured.value` as authored data governed by that run's `flow_version` and `structured.output_contract`; do not infer another envelope inside it.",
            "For `artifact`, use the file id from `result.files`, then call `runtime_paths.artifact_signed_url_template` to get a short-lived download URL.",
            "Use `inline_text` as complete exact text. A `file_backed_text` preview is only a bounded prefix. Download `file` through `runtime_paths.artifact_signed_url_template` only when its availability is `available`; when it is `content_purged`, the complete text is unavailable and the artifact request returns `410`.",
            "Treat `outbound_http.delivery_status: delivered` as a receipt, not as a copy of destination configuration or payload data.",
            "Call `runtime_paths.list_steps_template` only when the UI needs intermediate results, diagnostics, or step progress.",
            "`output_payload_json.text` is complete only when `output_payload_json.text_overflow` is absent; when present, `text` is a bounded preview and its single `generated_file_ids` entry identifies the current-attempt `generated_output` item in `result_files`.",
            "Download that file only when `availability` is `available`; `content_purged` leaves the preview incomplete and the artifact endpoint returns `410`. Final-result consumers should prefer the run-level `result`.",
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
                "test_openapi_flow_run_result_is_closed_and_exhaustively_discriminated",
            ),
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_flow_run_public_projects_text_artifact_and_outbound_results",
            ),
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_flow_run_public_projects_file_backed_text_overflow",
            ),
            TestReceipt(
                CONSUMER_API_TEST_FILE,
                "test_flow_run_list_uses_historical_contracts_with_bounded_bulk_queries",
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
            "If a Flow is republished while a run is being created, `flow_run_stale_version` tells you to refetch the run contract and resubmit the intended run.",
            "Call `runtime_paths.cancel_run_template` when the user intentionally abandons a non-terminal run.",
            "Call `runtime_paths.redispatch_run_template` only for stale queued recovery. For accepted or outcome-unknown exhaustion, send the observed `dispatch_exhausted_at` as `expected_dispatch_exhausted_at` to rearm that epoch. A zero `redispatched_count` means no broker acceptance was confirmed; poll the returned run.",
            "Back off polling when `status_capabilities.should_poll` is false.",
            "Use run and step polling as the source of truth for status changes.",
            "Before submitting a batch, call `/api/v1/flows/runs/capacity/` and read `available_slots` for your tenant, instead of discovering the ceiling as a `flow_run_concurrency_limit_reached` rejection partway through. It is a snapshot, not a reservation, so `create_run` stays the authority.",
        ),
        runtime_path_fields=(
            "create_run",
            "cancel_run_template",
            "redispatch_run_template",
            "get_run_template",
        ),
        endpoint_operation_ids=("get_flow_run_capacity",),
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
    "evidence": "When a product needs explainability or cost visibility, read the evidence view and page provider calls without losing lifecycle state.",
    "human-in-the-loop": "After inputs are bound, plan how the UI behaves when a review-marked step pauses the run.",
    "mid-run-files": "If a user asks for files during execution, route the product design through review or rerun instead of inventing an unsupported upload path.",
    "results": "Once review is resolved, drive the result screen from the run's typed final result and open step details only when needed.",
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
    "webhook_deliveries": [],
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
    "text": "Hello and welcome to the annual review...",
    "structured": {"transcription": "Hello and welcome to the annual review..."},
}
WORKED_EXAMPLE_TRANSCRIPTION_EDITED: dict[str, object] = {
    "text": "Corrected transcription for the annual review.",
    "structured": {"transcription": "Corrected transcription for the annual review."},
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
WORKED_EXAMPLE_COMPLETED_RUN_RESPONSE: dict[str, object] = {
    **FLOW_RUN_PUBLIC_EXAMPLE,
    "revision": 3,
    "status": "completed",
    "dispatch_pending_since": None,
    "dispatch_next_attempt_at": None,
    "dispatched_at": "2026-03-17T10:05:01Z",
    "started_at": "2026-03-17T10:05:02Z",
    "finished_at": "2026-03-17T10:06:15Z",
    "result": {
        "kind": "artifact",
        "files": [WORKED_EXAMPLE_ARTIFACT_RESULT_FILE],
    },
    "result_files": [WORKED_EXAMPLE_ARTIFACT_RESULT_FILE],
    "updated_at": "2026-03-17T10:06:15Z",
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
        request_intro=(
            "Upload the audio file to the step that consumes audio input. Set the "
            "multipart file part's `Content-Type` to one of that step's "
            "`accepted_mimetypes` from the run contract."
        ),
        request_language="text",
        request_body=(
            "POST /api/v1/flows/{id}/steps/{step_id}/runtime-files/\n"
            "Content-Type: multipart/form-data\n\n"
            "upload_file=@review-audio.mp3;type=audio/mpeg"
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
        response_intro=(
            "The run reports review state and secret-free outbound delivery progress."
        ),
        response_json=FLOW_RUN_AWAITING_REVIEW_RESPONSE_EXAMPLE,
    ),
    WorkedExampleHop(
        title="Find active review",
        operation_id="get_active_flow_run_review_checkpoint",
        request_intro="Fetch the active checkpoint before showing the review screen. This endpoint always answers `200 OK`, and the body is the literal JSON `null` when no checkpoint is open, so check for that before reading any field.",
        request_language="text",
        request_body="GET /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
        response_intro="`review_mode` decides which controls to render: `edit` allows the full edit, approve, reject, resume path, while `view` allows approve, reject, and resume only. DOCX and PDF artifact steps can only ever use `view`.",
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
        request_intro="Approve the edited checkpoint with the latest revision. Approve carries no payload, and it does not restart the run; hop 8 does. To reject instead, post the same revision plus a required `reason` of 1 to 1024 characters, which cancels the run.",
        request_language="json",
        request_body=FLOW_RUN_REVIEW_CHECKPOINT_APPROVE_REQUEST_EXAMPLE,
        response_intro="The response records the approval and gives the revision used for resume.",
        response_json=WORKED_EXAMPLE_CHECKPOINT_APPROVED_RESPONSE,
    ),
    WorkedExampleHop(
        title="Resume run",
        operation_id="resume_flow_run_review_checkpoint",
        request_intro="Resume the run after approval so the worker can continue. `Idempotency-Key` is required here and nowhere else; send the same value on every retry of this one resume, because a different key against an already-resumed checkpoint returns `400 flow_review_already_resumed`.",
        request_language="json",
        request_body=FLOW_RUN_REVIEW_CHECKPOINT_RESUME_REQUEST_EXAMPLE,
        response_intro="The response is `202 Accepted` and returns the resumed checkpoint and the requeued run; the later steps have not run yet, so go back to polling.",
        response_json=WORKED_EXAMPLE_CHECKPOINT_RESUME_RESPONSE,
        request_headers=(
            (
                "Idempotency-Key",
                f"review-resume-{WORKED_EXAMPLE_CHECKPOINT['id']}",
            ),
        ),
    ),
    WorkedExampleHop(
        title="Read final run result",
        operation_id="get_flow_run",
        request_intro="Poll the resumed run until it completes, then branch on the closed `result.kind` discriminator.",
        request_language="text",
        request_body="GET /api/v1/flows/{id}/runs/{run_id}/",
        response_intro="This artifact result contains only current-attempt file metadata; use its file id for the authorized signed-URL request.",
        response_json=WORKED_EXAMPLE_COMPLETED_RUN_RESPONSE,
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


CLIENT_PITFALL_RULES: tuple[str, ...] = (
    "**Trailing slashes are load-bearing.** Every Flow runtime path ends with `/`, with one exception: `GET .../runs/{run_id}/evidence/export` has none. Requesting `/api/v1/flows/{id}/runs` without the slash returns `307 Temporary Redirect` to the slashed path. Some HTTP clients drop the request body or the authentication header when they follow a redirect, so send the exact path.",
    "**One credential per request.** `Authorization: Bearer` for a user token, `X-API-Key` for an API key. Never put an API key in the bearer header.",
    "**The active-checkpoint endpoint returns `200` with a body of literal `null`** when no checkpoint is open. It is not a `404` and not `{}`. Check for `null` before dereferencing.",
    "**Reject requires a `reason`.** `POST .../reject/` takes `expected_checkpoint_revision` and a non-empty `reason` of 1 to 1024 characters. Sending only the revision returns `400 flow_review_reject_reason_required`.",
    "**`Idempotency-Key` is required on resume and optional everywhere else.** `POST .../review-checkpoints/{checkpoint_id}/resume/` rejects a request without it (`400 flow_review_idempotency_key_required`). `POST /runs/` accepts it and it is strongly recommended. Edit, approve, and reject do not accept it at all; they use `expected_checkpoint_revision` for concurrency instead. Both accepted keys must be 1 to 255 characters after trimming, or the request returns `400 flow_run_invalid_idempotency_key`. That bound is enforced as a typed error rather than as a JSON Schema `maxLength`, so a validator generated from the OpenAPI document will not catch it for you.",
    "**Approve does not resume.** Approving records the decision; the run stays at `awaiting_review` until you call resume.",
    "**Edit replaces the whole payload.** `current_payload_json` is a full replacement, not a JSON Patch. Start from the payload the checkpoint returned, change only `text` and, when the step's `output_type` is `json`, `structured`, and resend every other key unchanged. Rebuilding the object from scratch drops runtime-owned keys and returns `400 typed_io_validation_failed`. When the payload carries `text_overflow` the `text` is a frozen preview that must be resent exactly as received; `structured` on that same checkpoint can still be edited.",
    "**`GET .../steps/` returns a bare JSON array**, not a pagination envelope. `GET /flows/` and `GET .../runs/` do return envelopes with `items` and `has_more`.",
    "**The upload's declared type must be right, and so must its bytes.** The multipart field is named `upload_file`, and that part's own `Content-Type` must be one of the step's `accepted_mimetypes` from the run contract. The server also sniffs the content and rejects a mismatch. Either failure returns `415`, and the response lists every accepted type.",
    "**Artifact downloads are two calls.** Ask for a signed URL, then `GET` that URL **without** an authentication header; the tenant is bound into the signature.",
    "**Cancel is a no-op on a terminal run.** `POST .../cancel/` on a run that already finished returns `200` with the run unchanged and still `completed` or `failed`. Read `status` from the response instead of assuming it is now `cancelled`. On a live run the status flips before the response returns, but the worker stops asynchronously: a completion-model call in flight is aborted within seconds, while a transcription or outbound HTTP call runs to completion and is honored only at the next step boundary.",
    '**An out-of-scope resource returns `403`, not `404`.** Scope is checked before the resource is looked up, so a flow in another space is indistinguishable from one that does not exist. Both give `403 insufficient_scope` with `context.auth_layer: "api_key_scope"`.',
    "**`eneo_error_code` is not an identifier.** It is a legacy numeric category derived from the exception class, so unrelated failures share a value and it cannot tell two of them apart. The string `code` is the only field to branch on.",
)

RUN_STATE_DIAGRAM = """stateDiagram-v2
  [*] --> queued
  queued --> running: worker starts
  running --> awaiting_review: checkpoint opens
  awaiting_review --> queued: approved checkpoint resumes
  running --> completed: all steps complete
  running --> failed: step or runtime failure
  queued --> cancelled: user cancel or deleted flow
  running --> cancelled: user cancel or deleted flow
  awaiting_review --> cancelled: review rejected
  awaiting_review --> cancelled: review expired
  awaiting_review --> cancelled: user cancel or deleted flow
  completed --> queued: rerun accepted
  failed --> queued: rerun accepted"""

POLLING_CADENCE_LINES: tuple[str, ...] = (
    "- poll `GET /api/v1/flows/{id}/runs/{run_id}/` every **2 seconds** for the first 30 seconds, then every **5 seconds**, then every **15 seconds** after two minutes",
    "- stop as soon as `should_poll` is false for the current status, meaning the run is `completed`, `failed`, or `cancelled`",
    "- keep polling while the status is `awaiting_review`; a reviewer may act at any time, and the checkpoint can also expire",
    "- cap the total wait with your own deadline. Long audio transcription is minutes, not seconds",
)

RESULT_KIND_ROWS: tuple[tuple[str, str, str], ...] = (
    (
        "`inline_text`",
        "Plain text small enough to be returned in the response",
        "Read `text` directly",
    ),
    (
        "`file_backed_text`",
        "Plain text too large to inline; it was written to a file instead",
        "`preview` is a bounded prefix, never the whole text. Check `file.availability`, then download `file` through the signed-URL endpoint",
    ),
    (
        "`structured`",
        "JSON matching the final step's output contract",
        "Read `value`. `output_contract` is the schema that value satisfies, interpreted with the run's pinned `flow_version`",
    ),
    (
        "`artifact`",
        "One or more generated files, typically DOCX or PDF",
        "For each entry in `files`, check `availability`, then request a signed URL and `GET` it with no auth header",
    ),
    (
        "`outbound_http`",
        "The flow posted the result to a destination the flow author configured",
        "Nothing to download. `delivery_status` is always `delivered`, because the result only exists once delivery succeeded; use `webhook_deliveries` on the run for attempt history",
    ),
)

CURL_CLIENT_LISTING = r"""# API is the deployment origin plus its API prefix. The prefix is an operator
# setting, so read it from the paths in that deployment's /openapi.json.
API="https://eneo.example.se/api/v1"
KEY="sk_live_example"
FLOW="00000000-0000-0000-0000-000000000001"

# 1. Discover what the published flow expects.
curl -s -H "X-API-Key: $KEY" "$API/flows/$FLOW/run-contract/"
# -> published_flow_version, form_fields, steps_requiring_input[] (step_id,
#    accepted_mimetypes, max_files, max_file_size_bytes), steps_requiring_review[]

STEP="00000000-0000-0000-0000-000000000101"   # steps_requiring_input[0].step_id

# 2. Upload the audio. The part name is upload_file and its Content-Type must be
#    one of that step's accepted_mimetypes.
FILE_ID=$(curl -s -H "X-API-Key: $KEY" \
  -F "upload_file=@meeting.mp3;type=audio/mpeg" \
  "$API/flows/$FLOW/steps/$STEP/runtime-files/" | jq -r .id)

# 3. Create the run. Creating it also starts it; there is no separate start call.
RUN_ID=$(curl -s -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: meeting-2026-03-17-001" \
  -d "{\"expected_flow_version\":3,\"input_payload_json\":{},\"step_inputs\":{\"$STEP\":{\"file_ids\":[\"$FILE_ID\"]}}}" \
  "$API/flows/$FLOW/runs/" | jq -r .id)

# 4. Poll until terminal or awaiting_review.
curl -s -H "X-API-Key: $KEY" "$API/flows/$FLOW/runs/$RUN_ID/" | jq .status

# 5. When status is awaiting_review, read the open checkpoint. A 200 body of
#    literal null means nothing is open, so branch before using any field.
CP=$(curl -s -H "X-API-Key: $KEY" \
  "$API/flows/$FLOW/runs/$RUN_ID/review-checkpoints/active/")
if [ "$CP" = "null" ]; then
  echo "no checkpoint open yet; keep polling"
  exit 0
fi
CP_ID=$(jq -r .id <<<"$CP"); REV=$(jq -r .revision <<<"$CP")

# 6. Correct the transcript. The edit is a full replacement, so start from the
#    payload the checkpoint returned and change only text. Every other key is
#    runtime-owned and must come back unchanged.
#    When the payload carries text_overflow the text lives in a result file and
#    the payload holds a frozen preview, so text cannot be changed. Only
#    structured is still editable on such a checkpoint.
if jq -e '.current_payload_json | has("text_overflow")' <<<"$CP" >/dev/null; then
  echo "overflow-backed transcript: text is frozen, edit structured instead"
  exit 0
fi
BODY=$(jq -n \
  --argjson revision "$REV" \
  --argjson payload "$(jq -c .current_payload_json <<<"$CP")" \
  --arg text "Corrected transcript." \
  '{expected_checkpoint_revision: $revision,
    current_payload_json: ($payload + {text: $text})}')
REV=$(curl -s -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d "$BODY" \
  "$API/flows/$FLOW/runs/$RUN_ID/review-checkpoints/$CP_ID/" | jq -r .revision)

# 7. Approve. Approve carries no payload and does not resume the run.
REV=$(curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"expected_checkpoint_revision\":$REV}" \
  "$API/flows/$FLOW/runs/$RUN_ID/review-checkpoints/$CP_ID/approve/" | jq -r .revision)

# 8. Resume. Idempotency-Key is required here. Reuse the same key on every retry.
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: resume-$CP_ID" \
  -d "{\"expected_checkpoint_revision\":$REV}" \
  "$API/flows/$FLOW/runs/$RUN_ID/review-checkpoints/$CP_ID/resume/"
# -> 202 Accepted; keep polling the run

# 9. When the run is completed, download the artifact. Two calls: sign, then GET.
FID=$(curl -s -H "X-API-Key: $KEY" "$API/flows/$FLOW/runs/$RUN_ID/" \
  | jq -r '.result.files[0].file_id')
URL=$(curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"expires_in":3600,"content_disposition":"attachment"}' \
  "$API/flows/$FLOW/runs/$RUN_ID/artifacts/$FID/signed-url/" | jq -r .url)
curl -s -o protocol.docx "$URL"     # no auth header on the signed URL

# Optional: stop a run the user abandoned.
curl -s -X POST -H "X-API-Key: $KEY" "$API/flows/$FLOW/runs/$RUN_ID/cancel/"
"""

TYPESCRIPT_CLIENT_LISTING = r"""/** Minimal Eneo Flows runtime client. No dependencies. */
export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_review"
  | "completed"
  | "failed"
  | "cancelled";

export type ReviewCheckpointState =
  | "awaiting_review"
  | "edited"
  | "approved"
  | "rejected"
  | "resumed"
  | "cancelled"
  | "expired";

export type OutputType = "text" | "json" | "pdf" | "docx";
export type FileAvailability = "available" | "content_purged";

export interface ResultFile {
  file_id: string;
  step_id: string;
  step_order: number;
  name: string;
  size: number;
  mimetype: string | null;
  file_type: "text" | "image" | "audio" | "document";
  source: "generated_output" | "declared_artifact";
  availability: FileAvailability;
}

/** Discriminated by `kind`; the union is closed. Field names come from the schemas. */
export type RunResult =
  | { kind: "inline_text"; text: string }
  | { kind: "file_backed_text"; file: ResultFile; preview: string }
  | { kind: "structured"; value: unknown; output_contract: unknown | null }
  | { kind: "artifact"; files: ResultFile[] }
  | { kind: "outbound_http"; delivery_status: "delivered" };

export interface FlowRun {
  id: string;
  flow_id: string;
  flow_version: number;
  revision: number;
  status: RunStatus;
  result: RunResult | null;
  result_files: ResultFile[];
  error: { code: string; message: string } | null;
  started_at: string | null;
  finished_at: string | null;
  /** Present on GET (FlowRunDetailPublic); empty unless the flow posts outbound. */
  webhook_deliveries?: unknown[];
}

/**
 * Only `text` and `structured` may be edited. Every other key is runtime-owned
 * and must be sent back unchanged, which is why the index signature is here:
 * the payload is not a closed shape a client may rebuild from scratch.
 */
export interface ReviewPayload {
  text: string;
  structured?: unknown;
  /** Present when the text was too large to inline. Its presence freezes `text`. */
  text_overflow?: unknown;
  [runtimeOwned: string]: unknown;
}

export interface ReviewCheckpoint {
  id: string;
  step_id: string;
  step_order: number;
  state: ReviewCheckpointState;
  revision: number;
  schema_version: number;
  review_mode: "view" | "edit";
  output_type: OutputType;
  output_contract: unknown | null;
  current_payload_json: ReviewPayload;
  expires_at: string;
}

/** The JSON body of every 4xx and 5xx response. Branch on `code`, never `message`. */
export interface EneoErrorBody {
  message: string;
  code: string;
  eneo_error_code?: number;
  context?: Record<string, unknown> | null;
  request_id?: string | null;
}

export class EneoApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: EneoErrorBody,
  ) {
    super(body.message);
  }
  get code(): string {
    return this.body.code;
  }
}

export class EneoFlows {
  /**
   * @param apiBase the deployment origin plus its API prefix, with no trailing
   *   slash, for example `https://eneo.example.se/api/v1`. The prefix is an
   *   operator setting, so read it from the paths in that deployment's
   *   `/openapi.json` instead of hardcoding one.
   */
  constructor(
    private readonly apiBase: string,
    private readonly apiKey: string,
  ) {}

  private async call<T>(
    method: string,
    path: string,
    init: { body?: unknown; form?: FormData; idempotencyKey?: string } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { "X-API-Key": this.apiKey };
    if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
    let body: BodyInit | undefined;
    if (init.form) {
      body = init.form; // never set Content-Type by hand for multipart
    } else if (init.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(init.body);
    }
    // Trailing slashes are load-bearing: without them the API answers 307.
    const res = await fetch(`${this.apiBase}${path}`, { method, headers, body });
    const text = await res.text();
    const parsed: unknown = text ? JSON.parse(text) : null;
    if (!res.ok) {
      throw new EneoApiError(
        res.status,
        (parsed ?? { message: res.statusText, code: "unknown" }) as EneoErrorBody,
      );
    }
    return parsed as T;
  }

  /** Take the exact shape from FlowRunContractPublic in the deployment's /openapi.json. */
  runContract(flowId: string): Promise<unknown> {
    return this.call("GET", `/flows/${flowId}/run-contract/`);
  }

  /** The part name is `upload_file`; its Content-Type must match the step contract. */
  upload(flowId: string, stepId: string, file: File): Promise<{ id: string }> {
    const form = new FormData();
    form.append("upload_file", file, file.name);
    return this.call("POST", `/flows/${flowId}/steps/${stepId}/runtime-files/`, { form });
  }

  /** Creating a run also starts it. There is no separate start call. */
  createRun(
    flowId: string,
    payload: {
      expected_flow_version: number;
      input_payload_json?: Record<string, unknown> | null;
      step_inputs?: Record<string, { file_ids: string[] }>;
    },
    idempotencyKey: string,
  ): Promise<FlowRun> {
    return this.call("POST", `/flows/${flowId}/runs/`, { body: payload, idempotencyKey });
  }

  getRun(flowId: string, runId: string): Promise<FlowRun> {
    return this.call("GET", `/flows/${flowId}/runs/${runId}/`);
  }

  /** Returns a bare array, not a pagination envelope. */
  listSteps(flowId: string, runId: string): Promise<unknown[]> {
    return this.call("GET", `/flows/${flowId}/runs/${runId}/steps/`);
  }

  /** Answers 200 with a literal null body when no checkpoint is open. */
  activeCheckpoint(flowId: string, runId: string): Promise<ReviewCheckpoint | null> {
    return this.call("GET", `/flows/${flowId}/runs/${runId}/review-checkpoints/active/`);
  }

  /**
   * The edit is a full replacement, so it takes the checkpoint the server
   * returned and merges the reviewer's changes onto its payload. Rebuilding the
   * payload from scratch drops runtime-owned keys and fails validation with
   * `typed_io_validation_failed`.
   */
  editCheckpoint(
    flowId: string,
    runId: string,
    checkpoint: ReviewCheckpoint,
    changes: { text?: string; structured?: unknown },
  ): Promise<ReviewCheckpoint> {
    const current = checkpoint.current_payload_json;
    const changesText = changes.text !== undefined && changes.text !== current.text;
    if (changesText && current.text_overflow !== undefined) {
      // The text lives in a result file and the payload only carries a frozen
      // preview of it. `structured` on the same checkpoint is still editable.
      throw new Error("overflow-backed text cannot be changed; edit structured instead");
    }
    return this.call(
      "PATCH",
      `/flows/${flowId}/runs/${runId}/review-checkpoints/${checkpoint.id}/`,
      {
        body: {
          expected_checkpoint_revision: checkpoint.revision,
          current_payload_json: { ...current, ...changes },
        },
      },
    );
  }

  approveCheckpoint(
    flowId: string,
    runId: string,
    checkpointId: string,
    expectedRevision: number,
  ): Promise<ReviewCheckpoint> {
    return this.call(
      "POST",
      `/flows/${flowId}/runs/${runId}/review-checkpoints/${checkpointId}/approve/`,
      { body: { expected_checkpoint_revision: expectedRevision } },
    );
  }

  /** `reason` is required, 1 to 1024 characters. Rejecting cancels the run. */
  rejectCheckpoint(
    flowId: string,
    runId: string,
    checkpointId: string,
    expectedRevision: number,
    reason: string,
  ): Promise<ReviewCheckpoint> {
    return this.call(
      "POST",
      `/flows/${flowId}/runs/${runId}/review-checkpoints/${checkpointId}/reject/`,
      { body: { expected_checkpoint_revision: expectedRevision, reason } },
    );
  }

  /**
   * Approve does not resume; this does. `Idempotency-Key` is required, and the
   * SAME key must be reused for every retry of this one logical resume.
   */
  resumeCheckpoint(
    flowId: string,
    runId: string,
    checkpointId: string,
    expectedRevision: number,
    idempotencyKey: string,
  ): Promise<{ checkpoint: ReviewCheckpoint; run: FlowRun }> {
    return this.call(
      "POST",
      `/flows/${flowId}/runs/${runId}/review-checkpoints/${checkpointId}/resume/`,
      { body: { expected_checkpoint_revision: expectedRevision }, idempotencyKey },
    );
  }

  /** Cancelling an already-terminal run is a 200 no-op, not an error. */
  cancelRun(flowId: string, runId: string): Promise<FlowRun> {
    return this.call("POST", `/flows/${flowId}/runs/${runId}/cancel/`);
  }

  /** Then GET the returned url with NO authentication header. */
  async artifactUrl(
    flowId: string,
    runId: string,
    fileId: string,
    expiresIn = 3600,
  ): Promise<string> {
    const res = await this.call<{ url: string; expires_at: number }>(
      "POST",
      `/flows/${flowId}/runs/${runId}/artifacts/${fileId}/signed-url/`,
      { body: { expires_in: expiresIn, content_disposition: "attachment" } },
    );
    return res.url;
  }

  /** Poll with a widening interval until the run stops needing attention. */
  async waitForRun(
    flowId: string,
    runId: string,
    opts: { deadlineMs?: number; onUpdate?: (run: FlowRun) => void } = {},
  ): Promise<FlowRun> {
    const deadline = Date.now() + (opts.deadlineMs ?? 30 * 60_000);
    const interval = (elapsed: number) =>
      elapsed < 30_000 ? 2_000 : elapsed < 120_000 ? 5_000 : 15_000;
    const start = Date.now();
    for (;;) {
      const run = await this.getRun(flowId, runId);
      opts.onUpdate?.(run);
      if (run.status === "completed" || run.status === "failed" || run.status === "cancelled") {
        return run;
      }
      if (run.status === "awaiting_review") return run; // hand control to the reviewer
      if (Date.now() > deadline) throw new Error(`run ${runId} still ${run.status} at deadline`);
      await new Promise((resolve) => setTimeout(resolve, interval(Date.now() - start)));
    }
  }
}"""


def _render_client_pitfalls() -> str:
    return "\n".join(
        (
            "### Rules that break clients when you miss them",
            "",
            "These are the parts of the contract that are easy to get subtly wrong. Read them before you write the client.",
            "",
            *(
                f"{index}. {rule}"
                for index, rule in enumerate(CLIENT_PITFALL_RULES, start=1)
            ),
        )
    )


def _render_run_state_machine() -> str:
    rows = tuple(
        (
            f"`{status.value}`",
            "yes" if capability.is_active else "no",
            "yes" if capability.should_poll else "no",
            "yes" if capability.is_terminal else "no",
            "yes" if capability.is_cancellable else "no",
            "yes" if capability.is_awaiting_review else "no",
            "yes" if capability.can_request_redispatch else "no",
            "yes" if capability.is_rerun_eligible else "no",
        )
        for status in FlowRunStatus
        for capability in (FLOW_RUN_STATUS_CAPABILITIES[status],)
    )
    return "\n".join(
        (
            "## The run state machine",
            "",
            "A run has exactly six statuses. `queued` and `running` are active work, `awaiting_review` means a human review checkpoint is open and nothing advances until it is approved and resumed, and `completed`, `failed`, and `cancelled` are terminal.",
            "",
            '<div className="flow-docs-mermaid-figure">',
            "",
            "```mermaid",
            RUN_STATE_DIAGRAM,
            "```",
            "",
            "</div>",
            "",
            "_Run status transitions. `completed` and `failed` are terminal for the original execution but can re-enter `queued` through an explicit step rerun; `cancelled` cannot._",
            "",
            "Do not hardcode this table: `GET /api/v1/flows/runs/status-capabilities/` returns the same matrix as JSON, so a client can drive its UI from the live contract.",
            "",
            render_markdown_table(
                (
                    "Status",
                    "Active",
                    "Keep polling",
                    "Terminal",
                    "Can cancel",
                    "Awaiting review",
                    "Can redispatch",
                    "Can rerun a step",
                ),
                rows,
            ),
            "",
            "The full state map, including review-checkpoint and rerun-operation states, is on [The run lifecycle](/docs/flows-for-developers/run-lifecycle).",
            "",
            "### How to wait for a run",
            "",
            "Polling is the only mechanism a caller controls for observing run status, because there is no client-registered subscription, server-sent events stream, or WebSocket. A flow author can design a terminal step that delivers its result over outbound HTTP, and that does signal successful completion to whatever receiver they configured, but it is not something the caller registers and it does not report failure or review states. A workable cadence:",
            "",
            *POLLING_CADENCE_LINES,
        )
    )


def _render_outputs_by_type() -> str:
    return "\n".join(
        (
            "## Reading outputs by type",
            "",
            "A finished run exposes its output in two places, and which one you use depends on the shape the flow was designed to produce.",
            "",
            "`run.result` is the typed final result and is the value to render. It is a closed discriminated union on `kind`:",
            "",
            render_markdown_table(
                ("`result.kind`", "What it means", "How to consume it"),
                RESULT_KIND_ROWS,
            ),
            "",
            "`result.kind` is predictable before the run starts: the run contract's `final_output.output_type` (`text`, `json`, `pdf`, `docx`) and `final_output.delivery` tell you which branch to build the UI for.",
            "",
            "`GET .../runs/{run_id}/steps/` is the per-step view and is where intermediate output lives. Two things about it repeatedly surprise integrators:",
            "",
            "- A transcription step's text arrives in that step's `output_payload_json.text`, not in the run's `input_payload_json`. When the audio was long the transcription model chunked it, and the text carries per-chunk headers such as `### 0:00 - 0:50`. Strip them if you display raw transcript.",
            "- More than one step can emit a `structured` payload, because an early source-reader step often emits one too. Take the **last** structured step output before the rendering step, ordered by `step_order`, not the first.",
            "",
            "There is no fifth output type for other files. Any generated file that is not the typed final result still appears in `run.result_files` and in the owning step's `result_files`, with its own `mimetype` and a `file_type` of `text`, `image`, `audio`, or `document`. Download it through the same signed-URL endpoint.",
            "",
            "Every downloadable file carries `availability`. When retention has purged the bytes it reads `content_purged`, the metadata row remains, and requesting a signed URL for it returns `410` with code `flow_run_artifact_content_unavailable`.",
        )
    )


def _render_limits() -> str:
    review_days = FLOW_REVIEW_EXPIRY_MAX_SECONDS // (24 * 60 * 60)
    return "\n".join(
        (
            "## Limits, timings, and quotas",
            "",
            "Read effective per-flow values from `GET /api/v1/flows/{id}/run-contract/`. The numbers below are the platform behavior behind those values, so a client knows what it is looking at and what it can never exceed.",
            "",
            "### Uploads",
            "",
            render_markdown_table(
                ("What", "Value"),
                (
                    (
                        "Effective per-file size",
                        "`steps_requiring_input[].max_file_size_bytes` in the run contract. It resolves to the smallest of the tenant admin limit, the deployment's storage ceiling, and a hard platform maximum of 2 GiB",
                    ),
                    (
                        "Effective files per step",
                        "`steps_requiring_input[].max_files`. The platform caps audio at 100 files and other types at 1000, and the default audio allowance is 10 per run",
                    ),
                    (
                        "Accepted types",
                        "`steps_requiring_input[].accepted_mimetypes`. The step's own list wins if the flow author narrowed it",
                    ),
                    (
                        "Audio and video types today",
                        "`audio/wav`, `audio/mpeg`, `audio/mp3`, `audio/mp4`, `audio/x-m4a`, `audio/ogg`, `audio/webm`, `video/mp4`, `video/webm`. Always read the contract rather than hardcoding this list",
                    ),
                    (
                        "Upload timeout budget",
                        "`runtime_upload_policy` in the run contract: minimum 120 s, 8 s per MiB, maximum 600 s, idle timeout 120 s",
                    ),
                    (
                        "Oversize handling",
                        "The size is checked after the request body has been received, so an oversized upload still spends the full transfer before returning `413`. Compare the file against `max_file_size_bytes` client-side before you start",
                    ),
                    (
                        "Audio duration",
                        "No cap. Long audio is split into five-minute segments automatically",
                    ),
                ),
            ),
            "",
            "The deployment ceiling is the value that surprises teams: a deployment that keeps file bytes inside PostgreSQL can cap audio far below the tenant policy. The run contract always reports the resolved number, so trust it over any figure written down elsewhere.",
            "",
            "### Text and payload sizes",
            "",
            "A single limit governs both: **1 MiB of UTF-8 bytes**, deployment-configurable through the `FLOW_MAX_INLINE_TEXT_BYTES` environment variable and not exposed as a tenant setting.",
            "",
            "- A step's text output above it is written to a file, and the run result arrives as `file_backed_text` instead of `inline_text`.",
            "- `input_payload_json` above it is rejected at run creation with `flow_run_input_payload_too_large`.",
            "- A review edit whose `text` is above it is rejected with `typed_io_validation_failed`, and the response's `context.max_inline_text_bytes` reports the limit in force.",
            "- A transcript above it fails the step with `typed_io_transcript_too_large` rather than overflowing to a file.",
            "",
            "### Review checkpoints",
            "",
            render_markdown_table(
                ("What", "Value"),
                (
                    (
                        "Deadline",
                        "`steps_requiring_review[].expires_after_seconds` in the run contract, and `expires_at` on the checkpoint",
                    ),
                    (
                        "Allowed range",
                        f"{FLOW_REVIEW_EXPIRY_MIN_SECONDS} seconds to {review_days} days, default 14 days. It is set per step when the flow is authored, and no runtime endpoint changes it",
                    ),
                    (
                        "What expiry does",
                        f"A background reconciler runs every {FLOW_REVIEW_EXPIRY_RECONCILE_INTERVAL_SECONDS} seconds and, for a checkpoint still open past `expires_at`, marks it `expired` and cancels the run with `error.code` `flow_review_expired`",
                    ),
                    (
                        "Timing you can promise",
                        "The run flips to `cancelled` within roughly a minute of the deadline, not at the instant it passes",
                    ),
                    (
                        "Late approval",
                        "Resume still works after `expires_at` if the approval was persisted before it. An already-expired checkpoint returns `400 flow_review_expired`",
                    ),
                ),
            ),
            "",
            "### Retries and recovery",
            "",
            "- **The runtime does not retry a failed provider call.** A model or transcription failure fails the step directly. The one exception is a single reissue when a provider rejects an unsupported response format, and it shares the original step deadline.",
            "- **Dispatch to the worker is retried up to 5 times**, with fixed delays of 30, 120, 300, and 900 seconds. A sweep looks for stale queued runs every 30 seconds. `dispatch_attempt_count`, `dispatch_next_attempt_at`, and `dispatch_exhausted_at` on the run report where that budget stands.",
            "- **`redispatch` is for a stale queued run only**, and needs the observed `dispatch_exhausted_at` echoed back as `expected_dispatch_exhausted_at`. A `redispatched_count` of `0` means nothing was eligible.",
            "- **`rerun` is for a completed or failed run**, re-executes one completed step, invalidates everything downstream, and requires a `reason`.",
            "- Never auto-retry a step whose provider work may have started. A rerun repeats every provider call in that step, including calls that already succeeded, and spends again.",
            "",
            "### Concurrency and rate",
            "",
            "- A tenant may have a limited number of active runs at once; the deployment default is 4. `GET /api/v1/flows/runs/capacity/` reports `active_runs`, `max_concurrent_runs`, and `available_slots` for the caller's tenant. It is a snapshot, not a reservation.",
            "- Exceeding it returns `429` with `Retry-After: 60` and code `flow_run_concurrency_limit_reached`.",
            "- API keys are separately rate-limited per hour by scope. No endpoint reports remaining quota, so treat a `429` without `flow_run_concurrency_limit_reached` as a request-rate rejection and back off.",
            "",
            "### Retention",
            "",
            'Run history retention is a tenant setting and is off by default, so runs and their files persist until an administrator configures a window. Once a window is configured, expiry deletes the run and step history outright; artifact bytes purged earlier leave metadata behind with `availability: "content_purged"`. Because create-run idempotency replay is tied to the retained run row, the practical replay window is the run\'s retention window.',
            "",
            "Abandoned uploads that were never attached to a run are not swept automatically. Delete them yourself with `DELETE /api/v1/flows/{id}/runtime-files/{file_id}/`; a file already bound to a run returns `409 flow_runtime_file_attached`.",
            "",
            "Once retention has removed a run row, its create-run `Idempotency-Key` no longer matches anything, so replaying that key creates a new run instead of returning the old one. Keep the run id, not the key, as your durable handle.",
            "",
            "## What this API does not offer",
            "",
            "These are product limits, not documentation gaps. Design around them rather than looking for an endpoint that does not exist.",
            "",
            "- **No client-registered run-status subscription.** No webhook you can register, no server-sent events, no WebSocket. Polling is the contract for a client. A flow author can separately configure a terminal step to POST its result to a destination, but that is designed into the flow, not requested by the caller.",
            "- **No resumable or chunked upload.** A runtime file is one `multipart/form-data` request. A failed upload restarts from the beginning, which is why the run contract publishes an upload timeout budget scaled to file size.",
            "- **No global machine-readable catalogue of accepted media types.** The accepted list is per flow and per step, and `GET /api/v1/flows/{id}/run-contract/` is the only authoritative source. Do not hardcode one.",
            "- **No rate-limit introspection.** Nothing reports an API key's remaining hourly quota; you discover exhaustion from a `429`.",
            "- **No stable format for transcription chunk markers.** The per-chunk headers a long transcript carries are a rendering detail of the transcription step, not a contract. Strip them defensively rather than parsing them.",
            "- **No mid-run file injection.** A review checkpoint edit changes only `text` and `structured`; it cannot attach a file. The one way to rebind uploaded files after a run starts is a step rerun with explicit `step_inputs` overrides.",
            "- **CORS is deployment configuration, not an API contract.** A browser app calling Eneo directly depends on the operator's allowed origins; a server-side proxy avoids the question entirely, and is the right place to keep a service key anyway.",
        )
    )


def _render_minimal_client() -> str:
    return "\n".join(
        (
            "## A complete minimal client",
            "",
            "The two listings below are the same journey twice: once as copy-pasteable `curl`, once as a self-contained TypeScript module. Both cover discovery, upload, create, poll, review, resume, and download. Neither needs a library.",
            "",
            "### curl",
            "",
            "```bash",
            CURL_CLIENT_LISTING,
            "```",
            "",
            "### TypeScript",
            "",
            "```ts",
            TYPESCRIPT_CLIENT_LISTING,
            "```",
        )
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
        contract = flow_runtime_endpoint_by_operation_id()[hop.operation_id]
        request_line = (
            f"{contract.method.upper()} "
            f"{build_flow_endpoint_template(contract.route_path, api_prefix=CONSUMER_DOCS_API_PREFIX)}"
        )
        lines = ["Request:", "", "```text", request_line, "```"]
        if header_block:
            lines.extend(("", header_block, "", "Body:"))
        else:
            lines.extend(("", "Body:"))
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
        "It is written to be complete on its own. Everything a client needs is stated explicitly: exact paths including trailing slashes, exact header names, exact request bodies, exact status values, and the error codes to branch on. Where a value is deployment-configurable, the page says so and names the endpoint that reports the effective value.",
        "",
        "Flows themselves are authored by people in the Eneo Builder. This page never asks you to create or edit a flow; it assumes someone has already published one.",
        "",
        f"Use the reference for the full field catalog: [Flow Runtime API Reference]({FLOW_API_GUIDE_HREF}). Use the [Flow error reference](/guides/flows/reference/errors) for the complete code catalog.",
        "",
        "## Before you start",
        "",
        "Use your Eneo deployment origin as the base URL. Eneo does not publish a shared hosted origin; every installation has its own, and it is given to you out of band. The live contract for the deployment you target is served by that same origin at `/openapi.json`, with interactive documentation at `/docs`.",
        "",
        "Paths in this guide are written under `/api/v1/`, which is the prefix the reference configuration ships. It is an operator setting (`API_PREFIX`), not a constant, so read the prefix once from the paths in that deployment's `/openapi.json`, build your base URL from it, and treat every path below as relative to that base.",
        "",
        "Authenticate every request with exactly one credential:",
        "",
        "```text",
        "Authorization: Bearer <user-access-token>",
        "```",
        "",
        "or:",
        "",
        "```text",
        "X-API-Key: <service-key>",
        "```",
        "",
        "Keep service keys in server-side code; a browser frontend should use a user access token or call through your own backend. Do not put a service key in the bearer-token header. See [Authentication & OIDC](/guides/authentication) for token setup.",
        "",
        _render_client_pitfalls(),
        "",
        _render_run_state_machine(),
        "",
        "### Choose a published Flow",
        "",
        "The worked example starts with a known Flow id. If your app needs discovery, call `GET /api/v1/flows/?space_id={space_id}&limit=50&offset=0`. A service key sees only published Flows in its scoped space. `count` is the number of items in the current page, not the total; increase `offset` while `has_more` is true. After choosing an id, `GET /api/v1/flows/{id}/published/` returns the runtime-safe projection and canonical runtime paths. Do not use the draft `GET /api/v1/flows/{id}/` view from a service-key runtime app.",
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
        _render_minimal_client(),
        "",
        _render_outputs_by_type(),
        "",
        _render_limits(),
        "",
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[0]),
        "",
        render_unsupported_callout(UNSUPPORTED_CALLOUTS[1]),
    )
    return render_page(
        GuidePage(
            slug=CONSUMER_GUIDE_PAGE_SLUG,
            title="Integrating Flows",
            purpose="This page is the authoritative guide for building an application on the Eneo Flows runtime API. It covers the whole runtime surface in the order a client calls it: discover a published flow, upload input files, create and start a run, poll it, handle a human review checkpoint, cancel or retry, and download outputs.",
            orientation="You are in the integration step of the consumer journey, where the published design becomes runtime calls and user-facing states.",
            body=body,
        )
    )


def write_flow_consumer_guide_page() -> None:
    write_page(FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH, render_flow_consumer_guide_page())


if __name__ == "__main__":
    write_flow_consumer_guide_page()
