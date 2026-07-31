import type {
  components,
  Flow,
  FlowClassificationRetentionPolicies,
  FlowClassificationRetentionPolicy,
  FlowClassificationRetentionPolicyPreviewRequest,
  FlowClassificationRetentionPolicyUpdate,
  FlowDocumentRenderLimits,
  FlowEvidencePolicy,
  FlowGraph,
  FlowGraphEdge,
  FlowGraphNode,
  FlowHttpRequestPreview,
  FlowHttpTestRequest,
  FlowHttpTestResponse,
  FlowHttpTransportError,
  FlowInputLimits,
  FlowPackageDependencyResolution,
  FlowPackageExportResponse,
  FlowPackageExportRequest,
  FlowPackageImportPlan,
  FlowPackageImportPlanStatus,
  FlowPackageImportPlanSummary,
  FlowPackageImportResourceBinding,
  FlowPackageImportResult,
  FlowPackageImportTargetState,
  FlowPackageLocalCandidate,
  FlowPackageModelCandidate,
  FlowPackageOmission,
  FlowPackageRequirementDataSensitivity,
  FlowPackageResourceSlotRef,
  FlowPackageValidation,
  FlowProviderCallEvidence,
  FlowProviderCallEvidencePage,
  FlowRetentionPolicy,
  FlowRetentionChangeConfirmation,
  FlowRetentionImpactPreview,
  FlowRetentionOrganizationPreviewRequest,
  FlowRetentionPolicyUpdate,
  FlowRun,
  FlowRunContract,
  FlowRunContractStepInput,
  FlowRunContractTemplateReadiness,
  FlowRunDebugAttempt,
  FlowRunDebugExport,
  FlowRunDebugInput,
  FlowRunDebugIoTypes,
  FlowRunDebugOutput,
  FlowRunDebugRag,
  FlowRunDebugRagReference,
  RetrievedPassage,
  FlowRunDebugStep,
  FlowRunError,
  FlowRunEvidence,
  FlowRunEvidenceExport,
  FlowRunEvidenceWithTypedSteps,
  FlowRunInputRevision,
  FlowRunOutputPayload,
  FlowRunRedispatchRequest,
  FlowRunRedispatchResult,
  FlowRunRerunInvalidatedStep,
  FlowRunRerunOperation,
  FlowRunReviewCheckpoint,
  FlowRunReviewCheckpointResumeResponse,
  FlowRunReviewCheckpointState,
  FlowRunResult,
  FlowRunResultFile,
  FlowRunRetention,
  FlowRunStatusCapabilities,
  FlowRunStatusCapability,
  FlowRunStep,
  FlowRunStepInput,
  FlowRunStepInputs,
  FlowRunTokenUsage,
  FlowRuntimePolicy,
  FlowRuntimePolicyUpdate,
  FlowRuntimeUploadPolicy,
  FlowSparse,
  FlowStep,
  FlowTemplateAsset,
  FlowTemplateInspection,
  FlowTemplatePlaceholder,
  LocalResourceBinding,
  LocalResourceKind,
  UploadedFile,
  operations
} from "@eneo/eneo-js";
import { resolveFlowRuntimeUploadInitialTimeoutMs } from "@eneo/eneo-js";
import type { FlowRuntimeUploadTimeoutEvent } from "@eneo/eneo-js";

type FlowRunCreateRequest = components["schemas"]["FlowRunCreateRequest"];
type FlowRunPublic = components["schemas"]["FlowRunPublic"];
type CreateFlowRunHeaders = NonNullable<operations["create_flow_run"]["parameters"]["header"]>;
type CreateFlowRunResponse =
  operations["create_flow_run"]["responses"][201]["content"]["application/json"];
type GetFlowRunResponse =
  operations["get_flow_run"]["responses"][200]["content"]["application/json"];
type ListFlowRunsResponse =
  operations["list_flow_runs"]["responses"][200]["content"]["application/json"];
type GetFlowRunStatusCapabilitiesResponse =
  operations["get_flow_run_status_capabilities"]["responses"][200]["content"]["application/json"];
type RerunFlowRunStepResponse =
  operations["rerun_flow_run_step"]["responses"][202]["content"]["application/json"];
type RerunFlowRunStepError =
  operations["rerun_flow_run_step"]["responses"][400]["content"]["application/json"];
type ExportFlowRunEvidenceResponse =
  operations["export_flow_run_evidence"]["responses"][200]["content"]["application/json"];
type ExportFlowRunEvidenceError =
  operations["export_flow_run_evidence"]["responses"][400]["content"]["application/json"];
type ListFlowRunProviderCallsResponse =
  operations["list_flow_run_provider_calls"]["responses"][200]["content"]["application/json"];
type ResumeFlowRunReviewCheckpointHeaders =
  operations["resume_flow_run_review_checkpoint"]["parameters"]["header"];
type FlowRunReviewCheckpointEvidence =
  components["schemas"]["FlowRunReviewCheckpointEvidencePublic"];

type PublicFlowLaunchAliasSmoke = {
  Flow: Flow;
  FlowClassificationRetentionPolicies: FlowClassificationRetentionPolicies;
  FlowClassificationRetentionPolicy: FlowClassificationRetentionPolicy;
  FlowClassificationRetentionPolicyPreviewRequest: FlowClassificationRetentionPolicyPreviewRequest;
  FlowClassificationRetentionPolicyUpdate: FlowClassificationRetentionPolicyUpdate;
  FlowDocumentRenderLimits: FlowDocumentRenderLimits;
  FlowEvidencePolicy: FlowEvidencePolicy;
  FlowGraph: FlowGraph;
  FlowGraphEdge: FlowGraphEdge;
  FlowGraphNode: FlowGraphNode;
  FlowHttpRequestPreview: FlowHttpRequestPreview;
  FlowHttpTestRequest: FlowHttpTestRequest;
  FlowHttpTestResponse: FlowHttpTestResponse;
  FlowHttpTransportError: FlowHttpTransportError;
  FlowInputLimits: FlowInputLimits;
  FlowPackageDependencyResolution: FlowPackageDependencyResolution;
  FlowPackageExportResponse: FlowPackageExportResponse;
  FlowPackageExportRequest: FlowPackageExportRequest;
  FlowPackageImportPlan: FlowPackageImportPlan;
  FlowPackageImportPlanStatus: FlowPackageImportPlanStatus;
  FlowPackageImportPlanSummary: FlowPackageImportPlanSummary;
  FlowPackageImportResourceBinding: FlowPackageImportResourceBinding;
  FlowPackageImportResult: FlowPackageImportResult;
  FlowPackageImportTargetState: FlowPackageImportTargetState;
  FlowPackageLocalCandidate: FlowPackageLocalCandidate;
  FlowPackageModelCandidate: FlowPackageModelCandidate;
  FlowPackageOmission: FlowPackageOmission;
  FlowPackageRequirementDataSensitivity: FlowPackageRequirementDataSensitivity;
  FlowPackageResourceSlotRef: FlowPackageResourceSlotRef;
  FlowPackageValidation: FlowPackageValidation;
  FlowProviderCallEvidence: FlowProviderCallEvidence;
  FlowProviderCallEvidencePage: FlowProviderCallEvidencePage;
  FlowRetentionPolicy: FlowRetentionPolicy;
  FlowRetentionChangeConfirmation: FlowRetentionChangeConfirmation;
  FlowRetentionImpactPreview: FlowRetentionImpactPreview;
  FlowRetentionOrganizationPreviewRequest: FlowRetentionOrganizationPreviewRequest;
  FlowRetentionPolicyUpdate: FlowRetentionPolicyUpdate;
  FlowRun: FlowRun;
  FlowRunContract: FlowRunContract;
  FlowRunContractStepInput: FlowRunContractStepInput;
  FlowRunContractTemplateReadiness: FlowRunContractTemplateReadiness;
  FlowRunDebugAttempt: FlowRunDebugAttempt;
  FlowRunDebugExport: FlowRunDebugExport;
  FlowRunDebugInput: FlowRunDebugInput;
  FlowRunDebugIoTypes: FlowRunDebugIoTypes;
  FlowRunDebugOutput: FlowRunDebugOutput;
  FlowRunDebugRag: FlowRunDebugRag;
  FlowRunDebugRagReference: FlowRunDebugRagReference;
  RetrievedPassage: RetrievedPassage;
  FlowRunDebugStep: FlowRunDebugStep;
  FlowRunError: FlowRunError;
  FlowRunEvidence: FlowRunEvidence;
  FlowRunEvidenceExport: FlowRunEvidenceExport;
  FlowRunEvidenceWithTypedSteps: FlowRunEvidenceWithTypedSteps;
  FlowRunOutputPayload: FlowRunOutputPayload;
  FlowRunRedispatchRequest: FlowRunRedispatchRequest;
  FlowRunRedispatchResult: FlowRunRedispatchResult;
  FlowRunRerunInvalidatedStep: FlowRunRerunInvalidatedStep;
  FlowRunRerunOperation: FlowRunRerunOperation;
  FlowRunResult: FlowRunResult;
  FlowRunResultFile: FlowRunResultFile;
  FlowRunRetention: FlowRunRetention;
  FlowRunReviewCheckpoint: FlowRunReviewCheckpoint;
  FlowRunReviewCheckpointResumeResponse: FlowRunReviewCheckpointResumeResponse;
  FlowRunReviewCheckpointState: FlowRunReviewCheckpointState;
  FlowRunStatusCapabilities: FlowRunStatusCapabilities;
  FlowRunStatusCapability: FlowRunStatusCapability;
  FlowRunStep: FlowRunStep;
  FlowRunStepInput: FlowRunStepInput;
  FlowRunStepInputs: FlowRunStepInputs;
  FlowRunTokenUsage: FlowRunTokenUsage;
  FlowRuntimePolicy: FlowRuntimePolicy;
  FlowRuntimePolicyUpdate: FlowRuntimePolicyUpdate;
  FlowRuntimeUploadPolicy: FlowRuntimeUploadPolicy;
  FlowSparse: FlowSparse;
  FlowStep: FlowStep;
  FlowTemplateAsset: FlowTemplateAsset;
  FlowTemplateInspection: FlowTemplateInspection;
  FlowTemplatePlaceholder: FlowTemplatePlaceholder;
  LocalResourceBinding: LocalResourceBinding;
  LocalResourceKind: LocalResourceKind;
  UploadedFile: UploadedFile;
};

const isoTimestamp = "2026-03-17T10:05:00Z";
const flowId = "00000000-0000-0000-0000-000000000001";
const stepId = "00000000-0000-0000-0000-000000000101";
const tenantId = "00000000-0000-0000-0000-000000000010";
const runId = "00000000-0000-0000-0000-000000000301";
const stepResultId = "00000000-0000-0000-0000-000000000501";
const resultFileId = "00000000-0000-0000-0000-000000000801";
const rerunOperationId = "00000000-0000-0000-0000-000000000901";
const reviewCheckpointId = "00000000-0000-0000-0000-000000000905";

const validRuntimeUpload: UploadedFile = {
  id: "00000000-0000-0000-0000-000000000701",
  name: "review-audio.mp3",
  mimetype: "audio/mpeg",
  size: 1843200,
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validFlowPackageResourceSlotRef: FlowPackageResourceSlotRef = {
  kind: "model",
  slot: "structured",
  label: "Structured completion model"
};

const validFlowRunStatusCapability: FlowRunStatusCapability = {
  status: "completed",
  is_active: false,
  should_poll: false,
  is_terminal: true,
  is_cancellable: false,
  is_awaiting_review: false,
  can_request_redispatch: false,
  is_rerun_eligible: true
};

const validFlowRunStatusCapabilities: FlowRunStatusCapabilities = {
  statuses: [validFlowRunStatusCapability],
  filter_order: ["completed", "failed", "running", "queued", "awaiting_review", "cancelled"]
};

const validFlowStep: FlowStep = {
  id: stepId,
  assistant_id: "00000000-0000-0000-0000-000000000201",
  step_order: 1,
  input_source: "flow_input",
  input_type: "document",
  output_mode: "pass_through",
  output_type: "text",
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validFlow: Flow = {
  id: flowId,
  tenant_id: tenantId,
  space_id: "00000000-0000-0000-0000-000000000020",
  name: "Contract smoke flow",
  description: null,
  run_history_retention: {
    state: "days",
    effective_days: 14,
    effective_minimum_days: null,
    no_purge: false,
    policy_conflict: false,
    activation_sources: ["organization", "classification"],
    barrier_sources: [],
    contributors: {
      organization_days: 90,
      classification_days: 30,
      space_days: 14,
      flow_days: null,
      organization_minimum_days: null,
      classification_minimum_days: null,
      organization_no_purge: false,
      classification_no_purge: false
    }
  },
  steps: [validFlowStep],
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validRunContractStepInput: FlowRunContractStepInput = {
  step_id: stepId,
  step_order: 1,
  required: true,
  input_format: "document",
  accepted_mimetypes: ["application/pdf"]
};

const validRunContractTemplateReadiness: FlowRunContractTemplateReadiness = {
  step_id: stepId,
  status: "ready",
  can_edit: true,
  can_download: true,
  template_asset_id: "00000000-0000-0000-0000-000000000601",
  template_file_id: "00000000-0000-0000-0000-000000000602",
  template_name: "decision-template.docx",
  checksum: "sha256:template",
  published_flow_version: 3
};

const validRunContract: FlowRunContract = {
  flow_id: flowId,
  published_flow_version: 3,
  form_fields: [{ name: "case_id", type: "text", required: true }],
  runtime_upload_policy: {
    min_timeout_seconds: 120,
    seconds_per_mebibyte: 8,
    max_timeout_seconds: 600,
    idle_timeout_seconds: 120
  },
  steps_requiring_input: [validRunContractStepInput],
  template_readiness: [validRunContractTemplateReadiness]
};

const validStepInputs: FlowRunStepInputs = {
  [stepId]: {
    file_ids: ["00000000-0000-0000-0000-000000000701"]
  }
};
const validFlowRunStepInput: FlowRunStepInput = validStepInputs[stepId];

const validRuntimeUploadPolicy: FlowRuntimeUploadPolicy = {
  min_timeout_seconds: 120,
  seconds_per_mebibyte: 8,
  max_timeout_seconds: 600,
  idle_timeout_seconds: 120
};
resolveFlowRuntimeUploadInitialTimeoutMs(1024 * 1024, validRuntimeUploadPolicy);
const validRuntimeUploadTimeoutEvent: FlowRuntimeUploadTimeoutEvent = {
  reason: "stalled",
  timeoutMs: 120_000
};
validRuntimeUploadTimeoutEvent.timeoutMs.toFixed();

const validFlowRunResultFile: FlowRunResultFile = {
  flow_run_id: runId,
  flow_id: flowId,
  tenant_id: tenantId,
  step_result_id: stepResultId,
  step_id: stepId,
  step_order: 1,
  attempt_no: 1,
  file_id: resultFileId,
  ordinal: 0,
  source: "declared_artifact",
  name: "summary.pdf",
  checksum: "sha256:artifact",
  size: 14012,
  mimetype: "application/pdf",
  file_type: "document",
  availability: "available"
};

const validInlineTextResult: FlowRunResult = {
  kind: "inline_text",
  text: "Decision support generated."
};
const validFileBackedTextResult: FlowRunResult = {
  kind: "file_backed_text",
  preview: "Decision support preview.",
  file: {
    ...validFlowRunResultFile,
    source: "generated_output",
    name: "decision-support.txt",
    mimetype: "text/plain",
    file_type: "text"
  }
};
const validStructuredResult: FlowRunResult = {
  kind: "structured",
  value: {
    decision: "approve",
    authored_extension: { confidence: 0.9 }
  },
  output_contract: {
    type: "object",
    required: ["decision"]
  }
};
const validArtifactResult: FlowRunResult = {
  kind: "artifact",
  files: [validFlowRunResultFile]
};
const validOutboundResult: FlowRunResult = {
  kind: "outbound_http",
  delivery_status: "delivered"
};

function describeFlowRunResult(result: FlowRunResult): string {
  switch (result.kind) {
    case "inline_text":
      return result.text;
    case "file_backed_text":
      return result.file.name;
    case "structured":
      return JSON.stringify(result.value);
    case "artifact":
      return result.files.map((file) => file.name).join(", ");
    case "outbound_http":
      return result.delivery_status;
    default: {
      const unreachable: never = result;
      return unreachable;
    }
  }
}

function describeFlowRunInputRevision(revision: FlowRunInputRevision): string {
  switch (revision.status) {
    case "tracked":
      return revision.changed_paths.join(", ");
    case "not_recorded":
      return "not recorded";
    case "unavailable":
      return revision.reason;
    default: {
      const unreachable: never = revision;
      return unreachable;
    }
  }
}

const validFlowRun = {
  id: runId,
  flow_id: flowId,
  flow_version: 3,
  tenant_id: tenantId,
  trace_id: "00000000-0000-0000-0000-000000000302",
  revision: 1,
  status: "completed",
  dispatch_attempt_count: 1,
  input_payload_json: { case_id: "CASE-1" },
  result: validInlineTextResult,
  result_files: [validFlowRunResultFile],
  created_at: isoTimestamp,
  updated_at: isoTimestamp
} satisfies FlowRun & FlowRunPublic;

const validFlowRunOutputPayload: FlowRunOutputPayload = {
  text: "Decision support preview.",
  text_overflow: {
    generated_file_ids: [resultFileId],
    inline_text_bytes: 25,
    full_text_bytes: 4096
  }
};
const validFlowRunTokenUsage: FlowRunTokenUsage = {
  num_tokens_input: 120,
  num_tokens_output: 30,
  num_tokens_total: 150,
  input_completeness: "complete",
  output_completeness: "complete"
};
const validFlowRunError: FlowRunError = {
  schema_version: 1,
  code: "flow_step_execution_failed",
  message: "Step execution failed.",
  retryable: false
};
const validFlowRunRedispatchRequest: FlowRunRedispatchRequest = {
  expected_dispatch_exhausted_at: "2026-07-22T08:30:00Z"
};
const validFlowRunRedispatchResult: FlowRunRedispatchResult = {
  run: validFlowRun,
  redispatched_count: 1
};

const validCreateFlowRunResponse: CreateFlowRunResponse = validFlowRun;
const validGetFlowRunResponse: GetFlowRunResponse = {
  ...validFlowRun,
  webhook_deliveries: []
};
const validCreateFlowRunHeaders: CreateFlowRunHeaders = {
  "Idempotency-Key": "flow-run:client-request-1"
};
const validResumeFlowRunReviewCheckpointHeaders: ResumeFlowRunReviewCheckpointHeaders = {
  "Idempotency-Key": "flow-review-resume:checkpoint-1:3"
};

const validFlowRunStep: FlowRunStep = {
  id: stepResultId,
  flow_run_id: validFlowRun.id,
  flow_id: flowId,
  tenant_id: validFlowRun.tenant_id,
  step_id: stepId,
  step_order: 1,
  status: "completed",
  input_payload_json: { file_ids: validStepInputs[stepId].file_ids },
  output_payload_json: {
    text: "Step output"
  },
  current_attempt_no: 1,
  result_files: [validFlowRunResultFile],
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validRerunOperation: FlowRunRerunOperation = {
  id: rerunOperationId,
  tenant_id: tenantId,
  flow_id: flowId,
  flow_run_id: runId,
  rerun_step_id: stepId,
  rerun_step_order: 1,
  root_attempt_no: 2,
  root_attempt_id: "00000000-0000-0000-0000-000000000902",
  status: "completed",
  request_fingerprint: "sha256:rerun",
  expected_run_revision: 1,
  accepted_run_revision: 2,
  reason: "Refresh the source document.",
  input_revision: {
    status: "tracked",
    prior_input_hash: "sha256:prior",
    resulting_input_hash: "sha256:resulting",
    changed_paths: ["case_id"],
    prior_input_payload: { case_id: "CASE-1" }
  },
  input_payload: { case_id: "CASE-2" },
  root_step_input_override: {
    step_id: stepId,
    file_ids: ["00000000-0000-0000-0000-000000000702"]
  },
  root_step_input_override_requested: true,
  requested_by_principal_type: "user",
  requested_by_user_id: "00000000-0000-0000-0000-000000000030",
  failure_code: null,
  failure_message: null,
  started_at: isoTimestamp,
  finished_at: isoTimestamp,
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validRerunInvalidatedStep: FlowRunRerunInvalidatedStep = {
  id: "00000000-0000-0000-0000-000000000903",
  operation_id: rerunOperationId,
  tenant_id: tenantId,
  flow_id: flowId,
  flow_run_id: runId,
  step_id: stepId,
  step_order: 1,
  invalidation_order: 0,
  role: "root",
  dependency_sources_json: ["input_bindings.question"],
  prior_step_result_id: stepResultId,
  prior_attempt_id: "00000000-0000-0000-0000-000000000904",
  new_attempt_no: 2,
  new_attempt_id: validRerunOperation.root_attempt_id,
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validReviewCheckpoint: FlowRunReviewCheckpoint = {
  id: reviewCheckpointId,
  tenant_id: tenantId,
  flow_id: flowId,
  flow_run_id: runId,
  step_id: stepId,
  step_order: 1,
  attempt_no: 1,
  state: "resumed",
  revision: 3,
  schema_version: 1,
  original_payload_json: { text: "Draft answer." },
  current_payload_json: { text: "Reviewed answer." },
  step_label: "Review answer",
  review_mode: "edit",
  output_type: "json",
  output_contract: { type: "object", properties: { text: { type: "string" } } },
  next_step_ids: ["00000000-0000-0000-0000-000000000102"],
  requester_user_id: "00000000-0000-0000-0000-000000000030",
  requester_principal_type: "user",
  decided_by_user_id: "00000000-0000-0000-0000-000000000030",
  decided_by_principal_type: "user",
  edited_at: isoTimestamp,
  approved_at: isoTimestamp,
  rejected_at: null,
  resumed_at: isoTimestamp,
  cancelled_at: null,
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};
const validReviewCheckpointState: FlowRunReviewCheckpointState = validReviewCheckpoint.state;
const validReviewCheckpointResumeResponse: FlowRunReviewCheckpointResumeResponse = {
  checkpoint: validReviewCheckpoint,
  run: validFlowRun
};

const validReviewCheckpointEvidence: FlowRunReviewCheckpointEvidence = {
  ...validReviewCheckpoint,
  decision: "approved",
  resume_key_present: true
};

const validFlowGraph: FlowGraph = {
  nodes: [
    {
      id: stepId,
      label: "Collect source document",
      type: "step",
      step_order: 1
    }
  ],
  edges: []
};
const validFlowGraphNode: FlowGraphNode = validFlowGraph.nodes[0];
const validFlowGraphEdge: FlowGraphEdge = {
  source: stepId,
  target: "00000000-0000-0000-0000-000000000102",
  kind: "execution"
};

const validProviderCallEvidence: FlowProviderCallEvidence = {
  event_id: "00000000-0000-0000-0000-000000000501",
  attempt_id: "00000000-0000-0000-0000-000000000502",
  step_id: "00000000-0000-0000-0000-000000000503",
  step_order: 1,
  attempt_no: 1,
  ordinal: 1,
  status: "completed",
  request_schema_version: 2,
  provider_request_hash: "a".repeat(64),
  requested_model: "openai/gpt-4o-mini",
  provider: "openai",
  response_format: "json_schema",
  requested_capabilities: ["structured_output"],
  call_reason: "initial",
  mapped_execution_mode: null,
  mapped_item_index: null,
  mapped_source_index: null,
  mapped_source_id: null,
  response_model: "gpt-4o-mini-2026-07-01",
  provider_response_id: "response-1",
  num_tokens_input: 12,
  num_tokens_output: null,
  input_source: "provider",
  output_source: "not_reported",
  outcome_reason: null,
  requested_at: isoTimestamp,
  finished_at: isoTimestamp
};
const invalidProviderCallEvidenceWithNullCapabilities: FlowProviderCallEvidence = {
  ...validProviderCallEvidence,
  // @ts-expect-error provider-call capability evidence is always an observed array.
  requested_capabilities: null
};
const validProviderCallEvidenceWithNoRequestedCapabilities: FlowProviderCallEvidence = {
  ...validProviderCallEvidence,
  requested_capabilities: []
};
const {
  requested_capabilities: observedProviderCallCapabilities,
  ...providerCallEvidenceWithoutRequestedCapabilities
} = validProviderCallEvidence;
// @ts-expect-error provider-call evidence requires an observed capability array.
const invalidProviderCallEvidenceWithoutRequestedCapabilities: FlowProviderCallEvidence =
  providerCallEvidenceWithoutRequestedCapabilities;
const validProviderCallEvidencePage: FlowProviderCallEvidencePage = {
  items: [validProviderCallEvidence],
  count: 1,
  total_count: 1,
  has_more: false,
  next_after_event_id: null
};
const validListFlowRunProviderCallsResponse: ListFlowRunProviderCallsResponse =
  validProviderCallEvidencePage;

const validFlowEvidence: FlowRunEvidenceWithTypedSteps = {
  run: validFlowRun,
  definition_integrity: {
    status: "verified",
    expected_checksum: "sha256:definition",
    current_checksum: "sha256:definition"
  },
  definition_snapshot: { steps: [validFlowStep] },
  step_results: [validFlowRunStep],
  step_attempts: [],
  result_files: [validFlowRunResultFile],
  rerun_operations: [validRerunOperation],
  rerun_invalidated_steps: [validRerunInvalidatedStep],
  review_checkpoints: [validReviewCheckpointEvidence],
  webhook_deliveries: [],
  provider_calls: validProviderCallEvidencePage,
  debug_export: {
    schema_version: "eneo.flow.debug-export.v2",
    generated_at: isoTimestamp,
    run: {
      run_id: validFlowRun.id,
      flow_id: flowId,
      flow_version: validFlowRun.flow_version,
      status: validFlowRun.status,
      trace_id: validFlowRun.trace_id
    },
    definition: {
      flow_id: flowId,
      version: validFlowRun.flow_version,
      checksum: "sha256:definition",
      steps_count: 1
    },
    definition_snapshot: { steps: [validFlowStep] },
    steps: [],
    security: {
      redaction_applied: false,
      classification_field: "output_classification_override"
    }
  }
};
const validUntypedFlowEvidence: FlowRunEvidence = validFlowEvidence;

const validFlowEvidenceExport: FlowRunEvidenceExport = {
  schema_version: "flow-evidence-export.v16",
  generated_at: isoTimestamp,
  content_hash: "sha256:evidence",
  manifest: {
    schema_version: "flow-evidence-export.v16",
    app_version: "DEV",
    provenance_schema_version_min: "flow-attempt-provenance.v3",
    provenance_schema_version_current: "flow-attempt-provenance.v3",
    provenance_persisted_version_status: "not_tracked",
    content_hash: "sha256:evidence",
    content_hash_input: "redacted",
    exported_at: isoTimestamp,
    tenant_id: validFlowRun.tenant_id,
    run_id: validFlowRun.id,
    trace_id: validFlowRun.trace_id,
    flow_id: flowId,
    flow_version: validFlowRun.flow_version,
    actor: {
      type: "service_key",
      key_id: "00000000-0000-0000-0000-000000000040"
    },
    export_reason: "support_debug",
    detail_mode: "redacted",
    redaction_applied: false,
    masked_fields_count: 0,
    redaction_policy_version: "flow-evidence-redaction.v3",
    retention_state_summary: {
      tracking_state: "not_tracked",
      tombstone_count: 0,
      retention_purged_count: 0,
      artifact_content_purged_count: 0,
      redacted_for_deletion_count: 0,
      note: "Tombstone tracking is not yet exposed."
    },
    artifact_availability_summary: {
      tracking_state: "tracked",
      artifact_count: 1,
      available_count: 1,
      content_purged_count: 0,
      total_size_bytes: validFlowRunResultFile.size,
      artifacts: [validFlowRunResultFile],
      note: "Artifact availability is derived from flow_run_step_result_files."
    },
    review_checkpoint_summary: {
      count: 1,
      by_state: { resumed: 1 },
      any_edited: true,
      any_resumed: true,
      active_checkpoint_id: null,
      active_checkpoint_conflict: false
    }
  },
  summary: {
    status: "completed",
    trace_id: validFlowRun.trace_id,
    steps_count: 1,
    completed_steps: 1,
    failed_steps: 0,
    attempts_count: 1,
    artifacts_count: 1,
    artifact_names: [validFlowRunResultFile.name],
    artifact_details: [validFlowRunResultFile],
    duration_ms: 1000,
    models_used: ["gpt-5.4-nano"],
    rag_sources_count: 0,
    rag_source_names: [],
    rag_source_display_names: [],
    rag_sources: [],
    rag_usage_tracking: { tracking_state: "not_tracked" },
    citations: {},
    rerun_lineage: {
      operations_count: 0,
      queued_operations_count: 0,
      running_operations_count: 0,
      completed_operations_count: 0,
      failed_operations_count: 0,
      cancelled_operations_count: 0,
      active_operations_count: 0,
      terminal_operations_count: 0,
      invalidated_steps_count: 0,
      completed_replacement_count: 0
    },
    review_checkpoints: {
      count: 1,
      by_state: { resumed: 1 },
      any_edited: true,
      any_resumed: true,
      active_checkpoint_id: null,
      active_checkpoint_conflict: false
    },
    final_output: {
      kind: "artifact",
      text_present: false,
      text_preview: null,
      structured_present: false,
      artifact_count: 1,
      artifact_names: [validFlowRunResultFile.name],
      artifact_details: [validFlowRunResultFile]
    },
    step_overview: [
      {
        step_order: 1,
        step_id: stepId,
        user_description: validFlowStep.user_description,
        status: "completed",
        attempts_count: 1,
        retries: 0,
        duration_ms: 1000,
        models_used: ["gpt-5.4-nano"],
        knowledge_sources_count: 0,
        knowledge_usage_state: null,
        knowledge_retrieval: null,
        citations: {},
        artifact_names: [validFlowRunResultFile.name],
        artifact_details: [validFlowRunResultFile],
        result_output_kind: "artifact",
        output_summary: null,
        input_lineage: {
          input_source: "flow_input",
          used_question_binding: false,
          uses_runtime_input: false,
          runtime_input_format: null,
          runtime_file_count: 0,
          runtime_file_ids: [],
          runtime_file_names: [],
          runtime_file_checksums: [],
          runtime_files: [],
          question_binding_references_runtime_input: false,
          question_binding_expressions: [],
          upstream_step_orders: [],
          upstream_step_labels: []
        },
        configured_input_type: "text",
        configured_output_type: "docx",
        review_impact: {
          checkpoint_count: 1,
          any_edited: true,
          any_resumed: true,
          any_output_changed: true,
          last_event: {
            checkpoint_id: reviewCheckpointId,
            state: "resumed",
            decision: "approved",
            edited: true,
            resumed: true,
            attempt_no: 1,
            revision: 2,
            output_changed: true
          },
          events: [
            {
              checkpoint_id: reviewCheckpointId,
              state: "resumed",
              decision: "approved",
              edited: true,
              resumed: true,
              attempt_no: 1,
              revision: 2,
              output_changed: true
            }
          ]
        }
      }
    ]
  },
  redaction: {},
  bundle: validFlowEvidence
};

const validListFlowRunsResponse: ListFlowRunsResponse = {
  items: [validFlowRun],
  count: 1,
  has_more: false
};
const validStatusCapabilitiesResponse: GetFlowRunStatusCapabilitiesResponse =
  validFlowRunStatusCapabilities;
const validRerunFlowRunStepResponse: RerunFlowRunStepResponse = {
  operation_id: rerunOperationId,
  run: validFlowRun,
  rerun_step_id: stepId,
  new_attempt_no: 2,
  invalidated_step_ids: [stepId],
  status: "queued"
};
const validRerunFlowRunStepError: RerunFlowRunStepError = {
  message: "Flow run revision is stale.",
  eneo_error_code: 9007,
  code: "flow_run_rerun_stale_revision",
  context: { expected_run_revision: 4, current_run_revision: 5 }
};
const validExportFlowRunEvidenceResponse: ExportFlowRunEvidenceResponse = validFlowEvidenceExport;
const validExportFlowRunEvidenceError: ExportFlowRunEvidenceError = {
  message: "Raw evidence export requires an explicit non-default reason.",
  eneo_error_code: 9007,
  code: "flow_evidence_export_reason_required",
  context: { detail: "raw", default_reason: "support_debug" }
};

const invalidRunCreateRequest: FlowRunCreateRequest = {
  // @ts-expect-error top-level file_ids is not part of the generated create-run contract.
  file_ids: ["00000000-0000-0000-0000-000000000701"]
};

const invalidFlowStep = {
  ...validFlowStep,
  // @ts-expect-error generated Flow steps reject unknown input sources.
  input_source: "not-a-source"
} satisfies FlowStep;

// @ts-expect-error generated template assets require identifiers, checksum, and status.
const invalidTemplateAsset: FlowTemplateAsset = { name: "decision-template.docx" };

type OutdatedGraphNodeType = "input" | "llm" | "output";

// @ts-expect-error generated graph node type is backend-owned string, not the old frontend union.
const invalidGraphNodeType: OutdatedGraphNodeType = validFlowGraph.nodes[0].type;

const invalidStepInputs: FlowRunStepInputs = {
  // @ts-expect-error frontend run intent requires populated file_ids per step.
  [stepId]: {}
};

// @ts-expect-error public rerun operations expose input_payload, not the raw JSONB column name.
validRerunOperation.input_payload_json = { case_id: "CASE-2" };

void validFlow;
void validRuntimeUpload;
void validFlowPackageResourceSlotRef;
void validRunContract;
void validRunContractStepInput;
void validRunContractTemplateReadiness;
void validFlowRunStepInput;
void validFlowRunStatusCapability;
void validFlowRunStatusCapabilities;
void validFlowRunOutputPayload;
void describeFlowRunResult(validInlineTextResult);
void describeFlowRunResult(validFileBackedTextResult);
void describeFlowRunResult(validStructuredResult);
void describeFlowRunResult(validArtifactResult);
void describeFlowRunResult(validOutboundResult);
void describeFlowRunInputRevision(validRerunOperation.input_revision);
void validFlowRunTokenUsage;
void validFlowRunError;
void validFlowRunRedispatchRequest;
void validFlowRunRedispatchResult;
void validCreateFlowRunResponse;
void validGetFlowRunResponse;
void validCreateFlowRunHeaders;
void validResumeFlowRunReviewCheckpointHeaders;
void validListFlowRunsResponse;
void validStatusCapabilitiesResponse;
void validRerunFlowRunStepResponse;
void validRerunFlowRunStepError;
void validExportFlowRunEvidenceResponse;
void validExportFlowRunEvidenceError;
void validFlowGraph;
void validFlowGraphNode;
void validFlowGraphEdge;
void validReviewCheckpointState;
void validReviewCheckpointResumeResponse;
void validFlowEvidence;
void validListFlowRunProviderCallsResponse;
void invalidProviderCallEvidenceWithNullCapabilities;
void validProviderCallEvidenceWithNoRequestedCapabilities;
void observedProviderCallCapabilities;
void invalidProviderCallEvidenceWithoutRequestedCapabilities;
void validUntypedFlowEvidence;
void validFlowEvidenceExport;
void invalidRunCreateRequest;
void invalidFlowStep;
void invalidTemplateAsset;
void invalidGraphNodeType;
void invalidStepInputs;
