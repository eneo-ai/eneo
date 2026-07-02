from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, assert_never

from eneo.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FLOW_TYPED_IO_ERROR_CODES,
    FlowApiErrorCode,
)

FlowErrorCategory = Literal[
    "Flow access",
    "Run input",
    "Run lifecycle",
    "Evidence and artifacts",
    "Published definition",
    "Step runtime",
    "Typed input/output",
    "Review checkpoint",
    "Template asset",
    "Rerun",
]

FlowErrorSurface = Literal[
    "API error response",
    "Run error payload",
    "API response and run error payload",
]
FlowErrorHandlingPhase = Literal[
    "Request path",
    "Run execution",
    "Request path or run execution",
]

_MAX_FIELD_LENGTH = 180
_SENTENCE_END_PATTERN = re.compile(r"[.!?]")


@dataclass(frozen=True, slots=True)
class FlowErrorTaxonomyEntry:
    category: FlowErrorCategory
    surfaced_through: FlowErrorSurface
    cause: str
    consumer_action: str
    user_action: str

    @property
    def handling_phase(self) -> FlowErrorHandlingPhase:
        surface = self.surfaced_through
        if surface == "API error response":
            return "Request path"
        if surface == "Run error payload":
            return "Run execution"
        if surface == "API response and run error payload":
            return "Request path or run execution"
        assert_never(surface)


def _entry(
    category: FlowErrorCategory,
    surfaced_through: FlowErrorSurface,
    cause: str,
    consumer_action: str,
    user_action: str,
) -> FlowErrorTaxonomyEntry:
    return FlowErrorTaxonomyEntry(
        category=category,
        surfaced_through=surfaced_through,
        cause=cause,
        consumer_action=consumer_action,
        user_action=user_action,
    )


FLOW_ERROR_TAXONOMY: dict[FlowApiErrorCode, FlowErrorTaxonomyEntry] = {
    FlowApiErrorCode.FLOW_NOT_PUBLISHED: _entry(
        category="Flow access",
        surfaced_through="API error response",
        cause="The caller used a runtime action before the flow had a published version.",
        consumer_action="Publish the flow or refetch the runtime contract before retrying.",
        user_action="Publish the flow, then start the run again.",
    ),
    FlowApiErrorCode.FLOW_DELETED: _entry(
        category="Flow access",
        surfaced_through="Run error payload",
        cause="The flow was deleted while the run was queued or executing.",
        consumer_action="Stop polling this run and require a restored or new flow before retrying.",
        user_action="Restore or recreate the flow before starting another run.",
    ),
    FlowApiErrorCode.OWNER_REQUIRED: _entry(
        category="Flow access",
        surfaced_through="API error response",
        cause="The draft mutation needs an owner, tenant admin, or space owner.",
        consumer_action="Retry with a principal that can own or administer the draft.",
        user_action="Ask an owner or administrator to change the flow.",
    ),
    FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED: _entry(
        category="Flow access",
        surfaced_through="API error response",
        cause="A service key tried to read a draft definition without admin role.",
        consumer_action="Use an admin service key or call the published runtime endpoint.",
        user_action="Use an administrator service key or the published runtime contract.",
    ),
    FlowApiErrorCode.SERVICE_KEY_PRINCIPAL_NOT_SUPPORTED: _entry(
        category="Flow access",
        surfaced_through="API error response",
        cause="The endpoint requires a user principal rather than a service-key principal.",
        consumer_action="Call with a user session or choose a service-key-supported runtime endpoint.",
        user_action="Sign in as a user with access.",
    ),
    FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The retry key is empty or longer than the accepted limit.",
        consumer_action="Send a stable idempotency key between 1 and 255 characters.",
        user_action="Retry the request with a valid retry key.",
    ),
    FlowApiErrorCode.RUN_STALE_VERSION: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The published flow version changed before the run was accepted.",
        consumer_action="Refetch the runtime contract and submit against the current version.",
        user_action="Reload the flow and submit again.",
    ),
    FlowApiErrorCode.RUN_REQUIRED_STEP_INPUT_MISSING: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="One or more required runtime files were not attached to a step.",
        consumer_action="Read the run contract and attach files to every required runtime-input step.",
        user_action="Add the required files and start the run again.",
    ),
    FlowApiErrorCode.RUN_RUNTIME_INPUT_DISABLED: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="A request attached files to a step that does not accept runtime input.",
        consumer_action="Refetch the run contract and only attach files to compatible steps.",
        user_action="Attach files to a step that accepts runtime files.",
    ),
    FlowApiErrorCode.RUN_TOP_LEVEL_FILE_IDS_NOT_SUPPORTED: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The request used the removed top-level file_ids shape.",
        consumer_action="Send files through step_inputs keyed by runtime step id.",
        user_action="Use the current file-upload flow and try again.",
    ),
    FlowApiErrorCode.RUN_IDEMPOTENCY_CONFLICT: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The retry key was reused with different run input.",
        consumer_action="Retry with the original payload or choose a new idempotency key.",
        user_action="Start a new run or retry the exact original request.",
    ),
    FlowApiErrorCode.RUN_CONCURRENCY_LIMIT_REACHED: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The tenant or flow already has too many active runs.",
        consumer_action="Back off and retry after another run reaches a terminal status.",
        user_action="Wait for another run to finish, then try again.",
    ),
    FlowApiErrorCode.RUN_INVALID_STEP_INPUTS: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The step_inputs payload has invalid shape or file identifiers.",
        consumer_action="Validate step_inputs against the runtime contract before submitting.",
        user_action="Check the selected files and try again.",
    ),
    FlowApiErrorCode.RUN_UNKNOWN_STEP_INPUT: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The request references a step id outside the published run contract.",
        consumer_action="Refetch the runtime contract and remove stale step ids.",
        user_action="Reload the flow contract and try again.",
    ),
    FlowApiErrorCode.RUN_STEP_INPUT_MAX_FILES_EXCEEDED: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="A runtime-input step received more files than its policy allows.",
        consumer_action="Limit attached files per step to the contract max_files value.",
        user_action="Remove extra files and try again.",
    ),
    FlowApiErrorCode.RUN_FILE_NOT_ACCESSIBLE: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The caller cannot read one or more selected runtime files.",
        consumer_action="Upload the file through the same caller context or choose an accessible file.",
        user_action="Upload the files again or choose files you can access.",
    ),
    FlowApiErrorCode.RUN_FILE_NOT_BOUND_TO_FLOW: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="A selected runtime file belongs to another flow.",
        consumer_action="Upload files through the target flow before binding them to a run.",
        user_action="Upload the file through this flow and try again.",
    ),
    FlowApiErrorCode.RUN_STEP_INPUT_FILE_TOO_LARGE: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="An attached runtime file exceeds the step size limit.",
        consumer_action="Check max file size in the run contract before upload or binding.",
        user_action="Choose a smaller file.",
    ),
    FlowApiErrorCode.RUN_STEP_INPUT_MIMETYPE_REJECTED: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="An attached runtime file has a MIME type the step rejects.",
        consumer_action="Check accepted MIME types in the run contract before upload or binding.",
        user_action="Choose a compatible file type.",
    ),
    FlowApiErrorCode.RUN_AGGREGATE_MAX_FILES_EXCEEDED: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The run exceeds the total runtime-file count allowed across steps.",
        consumer_action="Reduce the total attached files before creating or rerunning the run.",
        user_action="Remove files and try again.",
    ),
    FlowApiErrorCode.RUN_RESERVED_INPUT_PAYLOAD_KEY: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The input payload used a key reserved for Flow orchestration.",
        consumer_action="Rename caller-owned payload fields that collide with reserved keys.",
        user_action="Rename the input field and try again.",
    ),
    FlowApiErrorCode.RUN_INPUT_PAYLOAD_TOO_LARGE: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The submitted run input payload exceeds the allowed size.",
        consumer_action="Reduce text, JSON fields, or file-derived payload before retrying.",
        user_action="Submit less text or fewer fields.",
    ),
    FlowApiErrorCode.RUN_ACCESS_DENIED: _entry(
        category="Flow access",
        surfaced_through="API error response",
        cause="The caller cannot access the requested run.",
        consumer_action="Check tenant, space, service-key scope, and run ownership before retrying.",
        user_action="Ask for access to the run.",
    ),
    FlowApiErrorCode.RUN_CANCELLED: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="The run reached cancelled before all steps completed.",
        consumer_action="Stop polling and create a new run only if the user still needs output.",
        user_action="Start a new run if you still need the result.",
    ),
    FlowApiErrorCode.RUN_USER_CANCELLED: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="A user cancelled the run while it was active.",
        consumer_action="Treat the terminal state as intentional and do not auto-retry.",
        user_action="Start a new run if you still need the result.",
    ),
    FlowApiErrorCode.RUN_DISPATCH_FAILED: _entry(
        category="Run lifecycle",
        surfaced_through="API response and run error payload",
        cause="The run could not be queued for worker execution.",
        consumer_action="Retry with backoff and alert an operator if dispatch keeps failing.",
        user_action="Retry the run or contact an administrator.",
    ),
    FlowApiErrorCode.RUN_MISSING_PRINCIPAL: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="The runtime could not resolve the principal that owns execution.",
        consumer_action="Check service-key ownership and tenant principal state before retrying.",
        user_action="Ask an administrator to check flow ownership.",
    ),
    FlowApiErrorCode.RUN_SERVICE_PRINCIPAL_DISABLED: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="The service principal for the run is disabled.",
        consumer_action="Choose an enabled service principal or re-enable the configured one.",
        user_action="Ask an administrator to enable the service principal.",
    ),
    FlowApiErrorCode.RUN_RUNTIME_ACTOR_INVALID: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="The runtime actor resolved from the run is no longer valid.",
        consumer_action="Refresh service-key or owner configuration before retrying.",
        user_action="Ask an administrator to check execution permissions.",
    ),
    FlowApiErrorCode.RUN_TASK_TIMEOUT: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="The worker task exceeded its execution deadline.",
        consumer_action="Retry with smaller input or inspect worker capacity and timeout settings.",
        user_action="Retry with smaller input or try again later.",
    ),
    FlowApiErrorCode.RUN_TASK_FAILURE: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="The worker task failed outside a more specific Flow error.",
        consumer_action="Inspect run logs and trace ids before retrying or escalating.",
        user_action="Retry the run or contact support with the run ID.",
    ),
    FlowApiErrorCode.RUN_WORKER_STALLED: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="The worker stopped updating an active run within the recovery window.",
        consumer_action="Redispatch only if capabilities allow it, then escalate recurring stalls.",
        user_action="Retry or contact support with the run ID.",
    ),
    FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID: _entry(
        category="Run lifecycle",
        surfaced_through="Run error payload",
        cause="The stored run error payload is invalid or no longer matches the public contract.",
        consumer_action="Treat the run as failed and contact support with the run ID.",
        user_action="Contact support with the run ID.",
    ),
    FlowApiErrorCode.RUN_EVIDENCE_FORBIDDEN: _entry(
        category="Evidence and artifacts",
        surfaced_through="API error response",
        cause="The caller lacks permission to view run evidence.",
        consumer_action="Request evidence access with a principal allowed by run and policy checks.",
        user_action="Ask for permission to view run evidence.",
    ),
    FlowApiErrorCode.RUN_EVIDENCE_RAW_EXPORT_FORBIDDEN: _entry(
        category="Evidence and artifacts",
        surfaced_through="API error response",
        cause="Policy blocks raw evidence export for this run.",
        consumer_action="Use the allowed evidence view or request a policy change.",
        user_action="Use the available evidence view or ask an administrator.",
    ),
    FlowApiErrorCode.RUN_ARTIFACT_NOT_FOUND: _entry(
        category="Evidence and artifacts",
        surfaced_through="API error response",
        cause="The requested artifact is absent from the run or not visible to the caller.",
        consumer_action="Refresh run evidence and only request listed artifact ids.",
        user_action="Reload the run and choose an available artifact.",
    ),
    FlowApiErrorCode.RUN_ARTIFACT_CONTENT_UNAVAILABLE: _entry(
        category="Evidence and artifacts",
        surfaced_through="API error response",
        cause="The artifact content was purged or is otherwise unavailable.",
        consumer_action="Show retention-aware messaging and avoid retry loops for purged content.",
        user_action="The artifact content is no longer available.",
    ),
    FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="The published definition checksum changed before execution.",
        consumer_action="Refetch the flow contract and start a run against the current publication.",
        user_action="Reload the flow and start a new run.",
    ),
    FlowApiErrorCode.DEFINITION_INVALID: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="The published flow definition failed runtime validation.",
        consumer_action="Block new runs until an editor fixes and republishes the flow.",
        user_action="Ask a flow editor to fix and republish the flow.",
    ),
    FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_MISSING: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="The published definition is missing its schema version.",
        consumer_action="Require republish through the current editor before retrying.",
        user_action="Ask a flow editor to republish the flow.",
    ),
    FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_UNSUPPORTED: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="The published definition uses a schema version this runtime cannot execute.",
        consumer_action="Republish with the current editor or upgrade the runtime before retrying.",
        user_action="Ask a flow editor to republish with the current editor.",
    ),
    FlowApiErrorCode.DEFINITION_FLOW_ID_INVALID: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="The published snapshot references an invalid flow id.",
        consumer_action="Treat the publication as corrupt and require republish before running.",
        user_action="Ask a flow editor to republish the flow.",
    ),
    FlowApiErrorCode.DEFINITION_STEPS_INVALID: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="The published snapshot has invalid step definitions.",
        consumer_action="Block execution and show the editor that the flow must be republished.",
        user_action="Ask a flow editor to fix the steps and republish.",
    ),
    FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="The published snapshot contains no executable steps.",
        consumer_action="Prevent run creation until at least one executable step is published.",
        user_action="Add an executable step, republish, and run again.",
    ),
    FlowApiErrorCode.ASSISTANT_SNAPSHOT_DRIFT: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="An assistant snapshot changed relative to the published flow snapshot.",
        consumer_action="Republish the flow so runtime dependencies match the stored snapshot.",
        user_action="Republish the flow and start a new run.",
    ),
    FlowApiErrorCode.INPUT_CONTRACT_INAPPLICABLE: _entry(
        category="Published definition",
        surfaced_through="Run error payload",
        cause="A step input contract conflicts with its authored question binding.",
        consumer_action="Remove the conflicting contract or question binding, then republish.",
        user_action="Ask a flow editor to fix the step input settings.",
    ),
    FlowApiErrorCode.STEP_MISSING: _entry(
        category="Step runtime",
        surfaced_through="Run error payload",
        cause="The runtime referenced a step missing from the published snapshot.",
        consumer_action="Require republish and do not retry the stale run.",
        user_action="Ask a flow editor to republish the flow.",
    ),
    FlowApiErrorCode.STEP_ATTEMPT_START_FAILED: _entry(
        category="Step runtime",
        surfaced_through="Run error payload",
        cause="The executor could not start the next step attempt.",
        consumer_action="Inspect run diagnostics and retry only after transient storage issues clear.",
        user_action="Retry the run or contact support with the run ID.",
    ),
    FlowApiErrorCode.STEP_EXECUTION_FAILED: _entry(
        category="Step runtime",
        surfaced_through="Run error payload",
        cause="A step handler failed without a more specific typed error.",
        consumer_action="Open step details and use the stored message to guide rerun or support.",
        user_action="Open the failed step, fix input or configuration, then rerun.",
    ),
    FlowApiErrorCode.WEBHOOK_DELIVERY_FAILED: _entry(
        category="Step runtime",
        surfaced_through="Run error payload",
        cause="The run completed but outbound webhook delivery failed.",
        consumer_action="Read the result through run and step endpoints because delivery retries are exhausted and no public redelivery endpoint exists.",
        user_action="Check the webhook destination, then read the result in Eneo.",
    ),
    FlowApiErrorCode.RUNTIME_FILE_EMPTY: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The uploaded runtime file has no content.",
        consumer_action="Reject empty files client-side before uploading when possible.",
        user_action="Choose a file with content and upload it again.",
    ),
    FlowApiErrorCode.RUNTIME_FILE_ATTACHED: _entry(
        category="Run input",
        surfaced_through="API error response",
        cause="The runtime file is already attached to persisted run state.",
        consumer_action="Do not delete files that are bound to run history.",
        user_action="Keep the file or purge the related run history through retention policy.",
    ),
    FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED: _entry(
        category="Evidence and artifacts",
        surfaced_through="API error response",
        cause="Evidence access could not be audited before returning protected data.",
        consumer_action="Retry later and alert operators if audit logging remains unavailable.",
        user_action="Try again later.",
    ),
    FlowApiErrorCode.EVIDENCE_EXPORT_REASON_REQUIRED: _entry(
        category="Evidence and artifacts",
        surfaced_through="API error response",
        cause="Raw evidence export was requested without an audit reason.",
        consumer_action="Collect and send a specific export reason with the request.",
        user_action="Enter a specific reason before exporting raw evidence.",
    ),
    FlowApiErrorCode.LLM_REQUEST_TIMEOUT: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The model request for a step exceeded the runtime timeout.",
        consumer_action="Retry with smaller input or route the flow to a faster model.",
        user_action="Retry with smaller input or choose a faster model.",
    ),
    FlowApiErrorCode.RUNTIME_INPUT_NOT_CONSUMED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="Runtime files were attached but the step input did not reference them.",
        consumer_action="Update the authored step to consume step_input data or omit the files.",
        user_action="Ask a flow editor to connect the uploaded files to the step.",
    ),
    FlowApiErrorCode.UNSUPPORTED_OUTPUT_MODE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step uses an output mode the runtime cannot execute.",
        consumer_action="Change the output mode and republish before starting another run.",
        user_action="Ask a flow editor to choose a supported output mode.",
    ),
    FlowApiErrorCode.UNSUPPORTED_OUTPUT_TYPE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step uses an output type the runtime cannot render.",
        consumer_action="Choose a supported output type and republish the flow.",
        user_action="Ask a flow editor to choose a supported output type.",
    ),
    FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION: _entry(
        category="Typed input/output",
        surfaced_through="API response and run error payload",
        cause="A submitted or generated value does not match the step output contract.",
        consumer_action="Fix the JSON shape against the contract before saving or rerunning.",
        user_action="Fix the structured output and save again.",
    ),
    FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step input or output failed validation without a more specific code.",
        consumer_action="Open step diagnostics and correct the input, schema, or configuration.",
        user_action="Open the step details, fix input or configuration, and rerun.",
    ),
    FlowApiErrorCode.TYPED_IO_AUDIO_INVALID_FILE_TYPE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="An audio step received a file type it cannot transcribe.",
        consumer_action="Validate accepted audio types before upload or rerun.",
        user_action="Upload a supported audio file and start again.",
    ),
    FlowApiErrorCode.TYPED_IO_AUDIO_MISSING_FILE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="An audio step expected a runtime file but none was available.",
        consumer_action="Attach the required audio file to the step before creating the run.",
        user_action="Attach the required audio file and start again.",
    ),
    FlowApiErrorCode.TYPED_IO_AUDIO_SOURCE_UNSUPPORTED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="An audio step uses an input source that runtime does not support.",
        consumer_action="Configure the step for runtime files or a supported previous step output.",
        user_action="Ask a flow editor to change the audio input source.",
    ),
    FlowApiErrorCode.TYPED_IO_AUDIO_TOO_MANY_FILES: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="An audio step received more files than it can process.",
        consumer_action="Attach exactly the allowed number of audio files before starting the run.",
        user_action="Remove extra audio files and start again.",
    ),
    FlowApiErrorCode.TYPED_IO_DOCUMENT_SOURCE_UNSUPPORTED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="A document step uses an input source runtime cannot read.",
        consumer_action="Configure the document step for a supported runtime input source.",
        user_action="Ask a flow editor to change the document input source.",
    ),
    FlowApiErrorCode.TYPED_IO_EMPTY_EXTRACTION: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="Text extraction produced no readable content from the submitted file.",
        consumer_action="Prompt the user for a readable file before rerunning.",
        user_action="Use a file with readable content and start again.",
    ),
    FlowApiErrorCode.TYPED_IO_FILE_NOT_FOUND: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="A required runtime file could not be found during step execution.",
        consumer_action="Upload the file again and bind it through the current run contract.",
        user_action="Upload the file again and rerun the step.",
    ),
    FlowApiErrorCode.TYPED_IO_FILE_SOURCE_UNSUPPORTED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="A file step uses an input source runtime cannot read.",
        consumer_action="Configure the file step for runtime files or a supported previous output.",
        user_action="Ask a flow editor to change the file input source.",
    ),
    FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The HTTP step could not connect to the target service.",
        consumer_action="Check target availability, DNS, and network allow rules before rerunning.",
        user_action="Check the target service and try again.",
    ),
    FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The authored HTTP step configuration is invalid.",
        consumer_action="Fix URL, method, headers, body, authentication, or response settings.",
        user_action="Ask a flow editor to fix the HTTP step configuration.",
    ),
    FlowApiErrorCode.TYPED_IO_HTTP_INVALID_URL: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The HTTP step URL is not a valid absolute http or https URL.",
        consumer_action="Store a valid absolute URL and republish the flow.",
        user_action="Ask a flow editor to fix the HTTP URL.",
    ),
    FlowApiErrorCode.TYPED_IO_HTTP_MALFORMED_RESPONSE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The HTTP response could not be parsed into the expected format.",
        consumer_action="Adjust the endpoint response or the step response parser settings.",
        user_action="Ask a flow editor to check the HTTP response format.",
    ),
    FlowApiErrorCode.TYPED_IO_HTTP_NON_SUCCESS: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The HTTP step received a non-success status code.",
        consumer_action="Handle the upstream status or change the target endpoint behavior.",
        user_action="Check the target endpoint and try again.",
    ),
    FlowApiErrorCode.TYPED_IO_HTTP_RESPONSE_TOO_LARGE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The HTTP response exceeded the step response-size limit.",
        consumer_action="Request less data or expose a narrower endpoint for the flow.",
        user_action="Ask a flow editor to reduce the HTTP response size.",
    ),
    FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The HTTP URL was blocked by network safety rules.",
        consumer_action="Use an allowed public endpoint or request an administrator policy review.",
        user_action="Use an allowed endpoint or ask an administrator.",
    ),
    FlowApiErrorCode.TYPED_IO_HTTP_TIMEOUT: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The HTTP request exceeded the step timeout.",
        consumer_action="Reduce the request scope or increase upstream responsiveness before rerun.",
        user_action="Try again later or ask a flow editor to reduce the request.",
    ),
    FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step input exceeds the runtime processing limit.",
        consumer_action="Reduce text, files, extracted content, or prompt context before rerun.",
        user_action="Submit smaller input and try again.",
    ),
    FlowApiErrorCode.TYPED_IO_INVALID_FILE_TYPE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="A runtime file has a type unsupported by the step.",
        consumer_action="Validate file type against the step contract before upload or rerun.",
        user_action="Upload a compatible file and start again.",
    ),
    FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step combines input sources that cannot run together.",
        consumer_action="Change the step input-source settings and republish.",
        user_action="Ask a flow editor to fix the input sources.",
    ),
    FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_POSITION: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step reads from a prior step position that cannot supply the input.",
        consumer_action="Reorder or reconfigure the flow before republishing.",
        user_action="Ask a flow editor to fix the step order or input source.",
    ),
    FlowApiErrorCode.TYPED_IO_INVALID_JSON_INPUT: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step expected JSON but received invalid JSON input.",
        consumer_action="Validate the JSON value before rerunning the step.",
        user_action="Fix the JSON input and try again.",
    ),
    FlowApiErrorCode.TYPED_IO_INVALID_OUTPUT_MODE_COMBINATION: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The output mode conflicts with the current step input or output settings.",
        consumer_action="Change the output mode combination and republish the flow.",
        user_action="Ask a flow editor to adjust the output settings.",
    ),
    FlowApiErrorCode.TYPED_IO_INVALID_SCHEMA: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step output schema is invalid.",
        consumer_action="Fix the JSON schema and republish before rerunning.",
        user_action="Ask a flow editor to fix the output schema.",
    ),
    FlowApiErrorCode.TYPED_IO_MISSING_REQUIRED_FILES: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="A typed runtime step did not receive required files.",
        consumer_action="Attach required files according to the step contract before rerun.",
        user_action="Attach the required files and start again.",
    ),
    FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The model output could not be parsed into the expected JSON shape.",
        consumer_action="Adjust prompt or schema, then rerun the failed step.",
        user_action="Ask a flow editor to adjust the prompt or schema.",
    ),
    FlowApiErrorCode.TYPED_IO_RENDER_FAILED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The generated document or rich output could not be rendered.",
        consumer_action="Inspect output content and document settings before rerunning.",
        user_action="Ask a flow editor to check output formatting.",
    ),
    FlowApiErrorCode.TYPED_IO_TEMPLATE_CHECKSUM_MISMATCH: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The DOCX template changed after the flow was published.",
        consumer_action="Republish the flow with the current template before rerunning.",
        user_action="Republish the flow with the current template.",
    ),
    FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The DOCX template could not be rendered with the step output.",
        consumer_action="Check placeholders and referenced step outputs before rerunning.",
        user_action="Ask a flow editor to fix the template placeholders.",
    ),
    FlowApiErrorCode.TYPED_IO_TRANSCRIPT_TOO_LARGE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The audio transcript is too large for the step.",
        consumer_action="Use shorter audio or split the task into smaller runs.",
        user_action="Use a shorter recording or split the audio.",
    ),
    FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_CONFIG_INVALID: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The transcription step has invalid language or model settings.",
        consumer_action="Fix transcription settings and republish before rerunning.",
        user_action="Ask a flow editor to fix transcription settings.",
    ),
    FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_EMPTY: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="Transcription completed but produced no text.",
        consumer_action="Ask for audio with clear speech before rerunning.",
        user_action="Use an audio file with speech and start again.",
    ),
    FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The transcription provider failed while processing audio.",
        consumer_action="Retry after checking audio quality and provider availability.",
        user_action="Check the audio quality and try again.",
    ),
    FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_MISSING: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The transcription step has no configured model.",
        consumer_action="Choose an available transcription model and republish.",
        user_action="Ask a flow editor to choose a transcription model.",
    ),
    FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_UNAVAILABLE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The configured transcription model is unavailable.",
        consumer_action="Choose another model or retry after provider recovery.",
        user_action="Choose another model or try again later.",
    ),
    FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_NOT_ENABLED: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="Transcription is disabled for the tenant or step.",
        consumer_action="Enable transcription or change the step input type before republish.",
        user_action="Enable transcription or ask a flow editor to change the step.",
    ),
    FlowApiErrorCode.TYPED_IO_UNSUPPORTED_TYPE: _entry(
        category="Typed input/output",
        surfaced_through="Run error payload",
        cause="The step uses an input type runtime cannot execute.",
        consumer_action="Change the input type and republish the flow.",
        user_action="Ask a flow editor to choose a supported input type.",
    ),
    FlowApiErrorCode.PUBLISHED_FORM_SCHEMA_INVALID: _entry(
        category="Published definition",
        surfaced_through="API error response",
        cause="The published flow form configuration is invalid.",
        consumer_action="Ask an editor to fix form fields and republish before running.",
        user_action="Ask a flow editor to fix the form fields.",
    ),
    FlowApiErrorCode.REVIEW_POLICY_INVALID: _entry(
        category="Review checkpoint",
        surfaced_through="Run error payload",
        cause="A reviewed step has an invalid review policy.",
        consumer_action="Fix the review policy on an executable step and republish.",
        user_action="Ask a flow editor to fix review settings.",
    ),
    FlowApiErrorCode.REVIEW_STALE_REVISION: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The checkpoint changed after the caller loaded it.",
        consumer_action="Refetch the checkpoint and retry with the latest revision.",
        user_action="Reload the review and try again.",
    ),
    FlowApiErrorCode.REVIEW_EXPIRED: _entry(
        category="Review checkpoint",
        surfaced_through="API response and run error payload",
        cause="The checkpoint deadline passed before the review finished.",
        consumer_action="Refetch the run and stop attempting review actions on the expired checkpoint.",
        user_action="Reload the run because the review deadline passed.",
    ),
    FlowApiErrorCode.REVIEW_NOT_ACTIVE: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The checkpoint is no longer in a state that accepts this action.",
        consumer_action="Reload the run and branch on the latest checkpoint state.",
        user_action="Reload the run before continuing.",
    ),
    FlowApiErrorCode.REVIEW_STEP_RESULT_NOT_FOUND: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The step result linked to the checkpoint is no longer available.",
        consumer_action="Reload evidence and avoid editing or approving a missing result.",
        user_action="Reload the run and try again.",
    ),
    FlowApiErrorCode.REVIEW_CHECKPOINT_NOT_FOUND: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The requested review checkpoint id does not exist for the run.",
        consumer_action="Refetch run review links and use a current checkpoint id.",
        user_action="Reload the run and try again.",
    ),
    FlowApiErrorCode.REVIEW_REJECT_REASON_REQUIRED: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The reject request did not include a non-empty reason.",
        consumer_action="Require a review rejection reason before submitting.",
        user_action="Enter a reason before rejecting the review.",
    ),
    FlowApiErrorCode.REVIEW_REJECT_REASON_TOO_LONG: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The rejection reason exceeded the accepted length.",
        consumer_action="Truncate or ask the user to shorten the reject reason.",
        user_action="Shorten the rejection reason and try again.",
    ),
    FlowApiErrorCode.REVIEW_IDEMPOTENCY_KEY_REQUIRED: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The resume request did not include an idempotency key.",
        consumer_action="Generate a stable retry key for each resume request.",
        user_action="Reload the run and try again.",
    ),
    FlowApiErrorCode.REVIEW_NOT_APPROVED: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The checkpoint has not been approved and cannot resume.",
        consumer_action="Submit approve before resume, then retry resume with a retry key.",
        user_action="Approve the review before resuming.",
    ),
    FlowApiErrorCode.REVIEW_ALREADY_RESUMED: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The approved checkpoint was already resumed.",
        consumer_action="Treat duplicate resume as completed and reload the run status.",
        user_action="Reload the run to see the latest status.",
    ),
    FlowApiErrorCode.REVIEW_REJECTED: _entry(
        category="Review checkpoint",
        surfaced_through="API response and run error payload",
        cause="The checkpoint was rejected and the run cannot continue.",
        consumer_action="Stop resume attempts and show the rejection reason if available.",
        user_action="The review was rejected and the run cannot resume.",
    ),
    FlowApiErrorCode.REVIEW_CANCELLED: _entry(
        category="Review checkpoint",
        surfaced_through="API error response",
        cause="The checkpoint was cancelled by run terminalization or cancellation.",
        consumer_action="Reload the run and stop actions against the cancelled checkpoint.",
        user_action="Reload the run before continuing.",
    ),
    FlowApiErrorCode.REVIEW_OPEN_ACTIVE_CONFLICT_INVARIANT: _entry(
        category="Review checkpoint",
        surfaced_through="Run error payload",
        cause="The run already had an active checkpoint when runtime tried to open another.",
        consumer_action="Reload the run and escalate with the run ID if the conflict remains.",
        user_action="Reload the run and contact support if the problem remains.",
    ),
    FlowApiErrorCode.REVIEW_OPEN_STEP_RESULT_INCOMPLETE_INVARIANT: _entry(
        category="Review checkpoint",
        surfaced_through="Run error payload",
        cause="Runtime tried to open review before the step result was complete.",
        consumer_action="Reload the run and escalate with the run ID if the state remains invalid.",
        user_action="Reload the run and contact support if the problem remains.",
    ),
    FlowApiErrorCode.REVIEW_OPEN_MULTIPLE_ACTIVE_CHECKPOINTS_INVARIANT: _entry(
        category="Review checkpoint",
        surfaced_through="Run error payload",
        cause="The run had multiple active checkpoints during review opening.",
        consumer_action="Reload the run and escalate with the run ID if multiple active rows remain.",
        user_action="Reload the run and contact support if the problem remains.",
    ),
    FlowApiErrorCode.TEMPLATE_INVALID_ARCHIVE: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="The uploaded file is not a valid DOCX archive.",
        consumer_action="Validate DOCX archives before upload when possible.",
        user_action="Choose a valid DOCX file and try again.",
    ),
    FlowApiErrorCode.TEMPLATE_CORRUPTED_ARCHIVE: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="The DOCX archive appears corrupted.",
        consumer_action="Ask the user to reopen and resave the file before upload.",
        user_action="Open and save the file again in Word, then retry.",
    ),
    FlowApiErrorCode.TEMPLATE_MACRO_NOT_ALLOWED: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="The uploaded template is macro-enabled and not allowed.",
        consumer_action="Accept only non-macro DOCX templates for Flow templates.",
        user_action="Save the file as DOCX without macros and try again.",
    ),
    FlowApiErrorCode.TEMPLATE_MISSING_REQUIRED_PARTS: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="The DOCX file lacks required document parts.",
        consumer_action="Reject the file and ask for a complete Word document template.",
        user_action="Choose a complete DOCX template and try again.",
    ),
    FlowApiErrorCode.TEMPLATE_NOT_ACCESSIBLE: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="The template file is not accessible to the caller or runtime actor.",
        consumer_action="Use a template stored in the flow or space with the right permissions.",
        user_action="Choose a template you can access.",
    ),
    FlowApiErrorCode.TEMPLATE_READ_ONLY: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="The caller can run the flow but cannot replace its template.",
        consumer_action="Hide template replacement for read-only callers.",
        user_action="Ask a flow editor to change the template.",
    ),
    FlowApiErrorCode.TEMPLATE_UNSUPPORTED_EXTENSION: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="The uploaded template file extension is not supported.",
        consumer_action="Allow only DOCX files for template upload.",
        user_action="Choose a DOCX file and try again.",
    ),
    FlowApiErrorCode.TEMPLATE_MISSING_CONTENT: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="The selected template record has no readable binary content.",
        consumer_action="Ask for a new upload or restore the template file content.",
        user_action="Choose or upload the template again.",
    ),
    FlowApiErrorCode.TEMPLATE_IN_USE: _entry(
        category="Template asset",
        surfaced_through="API error response",
        cause="A published flow definition still references the template asset.",
        consumer_action="Keep the template asset available while published versions can use it.",
        user_action="Unpublish or replace the published flow template before deleting it.",
    ),
    FlowApiErrorCode.RUN_RERUN_REASON_REQUIRED: _entry(
        category="Rerun",
        surfaced_through="API error response",
        cause="The rerun request did not include a non-empty reason.",
        consumer_action="Require a reason before submitting a rerun request.",
        user_action="Enter a reason before rerunning the step.",
    ),
    FlowApiErrorCode.RUN_RERUN_REASON_TOO_LONG: _entry(
        category="Rerun",
        surfaced_through="API error response",
        cause="The rerun reason exceeded the accepted length.",
        consumer_action="Truncate or ask the user to shorten the rerun reason.",
        user_action="Shorten the rerun reason and try again.",
    ),
    FlowApiErrorCode.RUN_RERUN_STALE_REVISION: _entry(
        category="Rerun",
        surfaced_through="API error response",
        cause="The run changed after the caller loaded it.",
        consumer_action="Refetch the run and submit rerun against the latest revision.",
        user_action="Reload the run and try rerun again.",
    ),
    FlowApiErrorCode.RUN_RERUN_INVALID_TRANSITION: _entry(
        category="Rerun",
        surfaced_through="API error response",
        cause="The run status cannot accept a step rerun.",
        consumer_action="Check status capabilities before showing or submitting rerun.",
        user_action="Reload the run before trying again.",
    ),
    FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND: _entry(
        category="Rerun",
        surfaced_through="API error response",
        cause="The selected rerun step is absent from the published snapshot.",
        consumer_action="Refetch run steps and only offer rerun for current step ids.",
        user_action="Reload the run and choose an available step.",
    ),
    FlowApiErrorCode.RUN_RERUN_STEP_INCOMPLETE: _entry(
        category="Rerun",
        surfaced_through="API error response",
        cause="The selected rerun step or dependency does not have a completed current result.",
        consumer_action="Offer rerun only for completed current step results.",
        user_action="Choose a completed step and try again.",
    ),
    FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID: _entry(
        category="Rerun",
        surfaced_through="API error response",
        cause="Rerun file overrides targeted a step other than the rerun root.",
        consumer_action="Attach rerun files only to the step being rerun.",
        user_action="Remove files from other steps and try again.",
    ),
    FlowApiErrorCode.RUN_RERUN_MULTIPLE_ACTIVE_OPERATIONS_INVARIANT: _entry(
        category="Rerun",
        surfaced_through="Run error payload",
        cause="The run had multiple active rerun operations during execution.",
        consumer_action="Reload the run and escalate with the run ID if multiple active operations remain.",
        user_action="Reload the run and contact support if the problem remains.",
    ),
    FlowApiErrorCode.RUN_RERUN_ATTEMPT_LINEAGE_CONFLICT_INVARIANT: _entry(
        category="Rerun",
        surfaced_through="Run error payload",
        cause="The rerun attempt history conflicted with an existing invalidated-step link.",
        consumer_action="Reload the run and escalate with the run ID if lineage remains inconsistent.",
        user_action="Reload the run and contact support if the problem remains.",
    ),
}

FLOW_ERROR_CATEGORY_ORDER: tuple[FlowErrorCategory, ...] = (
    "Flow access",
    "Run input",
    "Run lifecycle",
    "Evidence and artifacts",
    "Published definition",
    "Step runtime",
    "Typed input/output",
    "Review checkpoint",
    "Template asset",
    "Rerun",
)


def validate_flow_error_taxonomy(
    entries: Mapping[object, FlowErrorTaxonomyEntry] | None = None,
) -> None:
    selected_entries = FLOW_ERROR_TAXONOMY if entries is None else entries
    selected_keys = set(selected_entries)
    enum_keys = {key for key in selected_keys if isinstance(key, FlowApiErrorCode)}
    expected_keys = set(FlowApiErrorCode)
    missing = sorted(code.value for code in expected_keys - enum_keys)
    stale = sorted(str(key) for key in selected_keys - enum_keys)
    if missing or stale:
        raise ValueError(
            "Flow error taxonomy must match FlowApiErrorCode. "
            f"missing={missing}; stale={stale}"
        )

    for code, entry in selected_entries.items():
        if not isinstance(code, FlowApiErrorCode):
            continue
        if code in FLOW_TYPED_IO_ERROR_CODES and entry.category != "Typed input/output":
            raise ValueError(f"Flow error taxonomy category mismatch for {code.value}")
        if (
            code in FLOW_RUN_TERMINAL_ERROR_CODES
            and "run error payload" not in entry.surfaced_through.lower()
        ):
            raise ValueError(f"Flow error taxonomy surface mismatch for {code.value}")
        if (
            code not in FLOW_RUN_TERMINAL_ERROR_CODES
            and "run error payload" in entry.surfaced_through.lower()
        ):
            raise ValueError(f"Flow error taxonomy surface mismatch for {code.value}")
        _validate_short_sentence(code, "cause", entry.cause)
        _validate_short_sentence(code, "consumer_action", entry.consumer_action)
        _validate_short_sentence(code, "user_action", entry.user_action)


def _validate_short_sentence(
    code: FlowApiErrorCode,
    field_name: str,
    value: str,
) -> None:
    if "\n" in value or len(value) > _MAX_FIELD_LENGTH:
        raise ValueError(
            f"Flow error taxonomy {field_name} for {code.value} must be one sentence"
        )
    if len(_SENTENCE_END_PATTERN.findall(value)) > 1:
        raise ValueError(
            f"Flow error taxonomy {field_name} for {code.value} must be one sentence"
        )


validate_flow_error_taxonomy()
