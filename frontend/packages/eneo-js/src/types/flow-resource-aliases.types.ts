import type {
  components,
  Flow,
  FlowGraph,
  FlowRun,
  FlowRunContract,
  FlowRunEvidenceExport,
  FlowRunEvidenceWithTypedSteps,
  FlowRunRerunInvalidatedStep,
  FlowRunRerunOperation,
  FlowRunReviewCheckpoint,
  FlowRunResultFile,
  FlowRunStep,
  FlowRunStepInputs,
  FlowRuntimeUploadPolicy,
  FlowStep,
  FlowTemplateAsset,
  operations
} from "@eneo/eneo-js";
import { resolveFlowRuntimeUploadInitialTimeoutMs } from "@eneo/eneo-js";
import type { FlowRuntimeUploadTimeoutEvent } from "@eneo/eneo-js";

type FlowRunCreateRequest = components["schemas"]["FlowRunCreateRequest"];
type FlowRunPublic = components["schemas"]["FlowRunPublic"];
type CreateFlowRunResponse =
  operations["create_flow_run"]["responses"][201]["content"]["application/json"];
type GetFlowRunResponse =
  operations["get_flow_run"]["responses"][200]["content"]["application/json"];
type FlowRunReviewCheckpointEvidence =
  components["schemas"]["FlowRunReviewCheckpointEvidencePublic"];

const isoTimestamp = "2026-03-17T10:05:00Z";
const flowId = "00000000-0000-0000-0000-000000000001";
const stepId = "00000000-0000-0000-0000-000000000101";
const tenantId = "00000000-0000-0000-0000-000000000010";
const runId = "00000000-0000-0000-0000-000000000301";
const stepResultId = "00000000-0000-0000-0000-000000000501";
const resultFileId = "00000000-0000-0000-0000-000000000801";
const rerunOperationId = "00000000-0000-0000-0000-000000000901";
const reviewCheckpointId = "00000000-0000-0000-0000-000000000905";

const validFlowStep: FlowStep = {
  id: stepId,
  assistant_id: "00000000-0000-0000-0000-000000000201",
  step_order: 1,
  input_source: "flow_input",
  input_type: "document",
  output_mode: "pass_through",
  output_type: "text",
  mcp_policy: "inherit",
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validFlow: Flow = {
  id: flowId,
  tenant_id: tenantId,
  space_id: "00000000-0000-0000-0000-000000000020",
  name: "Contract smoke flow",
  description: null,
  steps: [validFlowStep],
  created_at: isoTimestamp,
  updated_at: isoTimestamp
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
  steps_requiring_input: [
    {
      step_id: stepId,
      step_order: 1,
      required: true,
      input_format: "document",
      accepted_mimetypes: ["application/pdf"]
    }
  ],
  template_readiness: [
    {
      step_id: stepId,
      status: "ready",
      can_edit: true,
      can_download: true,
      template_asset_id: "00000000-0000-0000-0000-000000000601",
      template_file_id: "00000000-0000-0000-0000-000000000602",
      template_name: "decision-template.docx",
      checksum: "sha256:template",
      published_flow_version: 3
    }
  ]
};

const validStepInputs: FlowRunStepInputs = {
  [stepId]: {
    file_ids: ["00000000-0000-0000-0000-000000000701"]
  }
};

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
  output_payload_json: {
    text: "Decision support generated."
  },
  result_files: [validFlowRunResultFile],
  created_at: isoTimestamp,
  updated_at: isoTimestamp
} satisfies FlowRun & FlowRunPublic;

const validCreateFlowRunResponse: CreateFlowRunResponse = validFlowRun;
const validGetFlowRunResponse: GetFlowRunResponse = validFlowRun;

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

const validFlowEvidence: FlowRunEvidenceWithTypedSteps = {
  run: validFlowRun,
  definition_snapshot: { steps: [validFlowStep] },
  step_results: [validFlowRunStep],
  step_attempts: [],
  result_files: [validFlowRunResultFile],
  rerun_operations: [validRerunOperation],
  rerun_invalidated_steps: [validRerunInvalidatedStep],
  review_checkpoints: [validReviewCheckpointEvidence],
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
      classification_field: "output_classification_override",
      mcp_policy_field: "mcp_policy"
    }
  }
};

const validFlowEvidenceExport: FlowRunEvidenceExport = {
  schema_version: "flow-evidence-export.v8",
  generated_at: isoTimestamp,
  content_hash: "sha256:evidence",
  manifest: {
    schema_version: "flow-evidence-export.v8",
    app_version: "DEV",
    provenance_schema_version_min: "flow-attempt-provenance.v1",
    provenance_schema_version_current: "flow-attempt-provenance.v1",
    provenance_persisted_version_status: "not_tracked",
    content_hash: "sha256:evidence",
    content_hash_input: "redacted",
    exported_at: isoTimestamp,
    tenant_id: validFlowRun.tenant_id,
    run_id: validFlowRun.id,
    trace_id: validFlowRun.trace_id,
    flow_id: flowId,
    flow_version: validFlowRun.flow_version,
    exported_by_user_id: null,
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
void validRunContract;
void validCreateFlowRunResponse;
void validGetFlowRunResponse;
void validFlowGraph;
void validFlowEvidence;
void validFlowEvidenceExport;
void invalidRunCreateRequest;
void invalidFlowStep;
void invalidTemplateAsset;
void invalidGraphNodeType;
void invalidStepInputs;
