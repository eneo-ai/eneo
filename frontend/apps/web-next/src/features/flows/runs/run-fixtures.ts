import type {
  ReviewCheckpoint,
  RunContract,
  RunDetail,
  RunGraph,
  RunResultFile,
  RunStep,
  RunSummary,
  RuntimeInput
} from "./runs-api";

/** Test fixtures for the run screens, in the shapes the core returns. */

export function makeInput(overrides: Partial<RuntimeInput> = {}): RuntimeInput {
  return {
    step_id: "step-1",
    step_order: 1,
    label: "Underlag",
    required: true,
    input_format: "document",
    accepted_mimetypes: ["application/pdf"],
    max_files: 3,
    max_file_size_bytes: 10 * 1024 * 1024,
    ...overrides
  };
}

export function makeContract(overrides: Partial<RunContract> = {}): RunContract {
  return {
    flow_id: "flow-1",
    published_flow_version: 3,
    form_fields: [],
    steps_requiring_input: [],
    steps_requiring_review: [],
    template_readiness: [],
    aggregate_max_files: null,
    runtime_upload_policy: {
      idle_timeout_seconds: 60,
      max_timeout_seconds: 600,
      min_timeout_seconds: 30,
      response_timeout_seconds: 120,
      seconds_per_mebibyte: 2
    },
    transcription: null,
    security_classification: null,
    ...overrides
  };
}

export function makeRunSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "run-1",
    flow_id: "flow-1",
    flow_version: 3,
    tenant_id: "tenant-1",
    trace_id: "trace-1",
    status: "completed",
    purpose: "production",
    principal_type: "user",
    started_by: {
      principal_type: "user",
      id: "user-1",
      display_name: "Anna Lind",
      email: "anna.lind@example.se"
    },
    revision: 3,
    dispatch_attempt_count: 1,
    created_at: "2026-10-21T08:00:00Z",
    started_at: "2026-10-21T08:00:02Z",
    finished_at: "2026-10-21T08:01:07Z",
    updated_at: "2026-10-21T08:01:07Z",
    ...overrides
  };
}

export function makeRunDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...makeRunSummary(),
    input_payload_json: { ärende: "Bygglov" },
    result: { kind: "inline_text", text: "Beslutet är fattat." },
    result_files: [],
    token_usage: {
      num_tokens_input: 1200,
      num_tokens_output: 300,
      num_tokens_total: 1500,
      input_completeness: "complete",
      output_completeness: "complete"
    },
    webhook_deliveries: [],
    evidence_access: {
      can_read_evidence: true,
      can_export_redacted: true,
      can_export_raw: true,
      read_refusal_code: null,
      redacted_export_refusal_code: null,
      raw_export_refusal_code: null
    },
    ...overrides
  };
}

export function makeRunStep(order: number, overrides: Partial<RunStep> = {}): RunStep {
  return {
    id: `result-${order}`,
    flow_id: "flow-1",
    flow_run_id: "run-1",
    tenant_id: "tenant-1",
    step_id: `step-${order}`,
    step_order: order,
    status: "completed",
    created_at: "2026-10-21T08:00:02Z",
    updated_at: "2026-10-21T08:00:30Z",
    started_at: "2026-10-21T08:00:02Z",
    finished_at: "2026-10-21T08:00:30Z",
    input_text_aliases: [],
    output_payload_json: { text: `Resultat från steg ${order}` },
    num_tokens_input: 600,
    num_tokens_output: 150,
    ...overrides
  };
}

export function makeResultFile(overrides: Partial<RunResultFile> = {}): RunResultFile {
  return {
    file_id: "file-1",
    name: "beslut.pdf",
    mimetype: "application/pdf",
    size: 2048,
    file_type: "document",
    availability: "available",
    checksum: "sha256:abc",
    ordinal: 1,
    attempt_no: 1,
    source: "generated_output",
    flow_id: "flow-1",
    flow_run_id: "run-1",
    tenant_id: "tenant-1",
    step_id: "step-1",
    step_order: 1,
    step_result_id: "result-1",
    ...overrides
  };
}

export function makeRunGraph(
  steps: { order: number; label: string; status: string | null }[]
): RunGraph {
  return {
    nodes: steps.map((step) => ({
      id: `step-${step.order}`,
      type: "step",
      label: step.label,
      step_order: step.order,
      run_status: step.status
    })),
    edges: []
  };
}

export function makeCheckpoint(overrides: Partial<ReviewCheckpoint> = {}): ReviewCheckpoint {
  return {
    id: "checkpoint-1",
    flow_id: "flow-1",
    flow_run_id: "run-1",
    tenant_id: "tenant-1",
    step_id: "step-2",
    step_order: 2,
    step_label: "Skriv svar",
    attempt_no: 1,
    state: "awaiting_review",
    review_mode: "edit",
    output_type: "text",
    revision: 1,
    schema_version: 1,
    requester_principal_type: "user",
    current_payload_json: { text: "Hej Anna, tack för ditt brev." },
    original_payload_json: { text: "Hej Anna, tack för ditt brev." },
    created_at: "2026-10-21T08:00:30Z",
    updated_at: "2026-10-21T08:00:30Z",
    // Far ahead so the default checkpoint stays open; expiry tests pass their own.
    expires_at: "2099-10-28T08:00:30Z",
    ...overrides
  };
}
