/**
 * Hand-written mirrors of the backend's flow models
 * (`backend/src/eneo/flows/{definition,flow_models}.py`) and the paths under
 * `/api/v1/flows`, in the shape `openapi-typescript` generates.
 *
 * TEMPORARY: replace with `Schema<"...">` and the generated `paths` once
 * `bun run gen:api` has run against a backend that serves these routes
 * (`src/lib/api/schema.d.ts`); `flows-api.ts` then drops its cast.
 */

// --- Definition -------------------------------------------------------------

export type FormFieldType = "text" | "number" | "select" | "file" | "audio";

export type FormField = {
  key: string;
  label: string;
  type: FormFieldType;
  required?: boolean;
  description?: string | null;
  options?: string[] | null;
};

export type StepKind = "llm" | "compose" | "document" | "review" | "transcribe";

type StepBase = {
  key: string;
  id?: string | null;
  name: string;
  description?: string | null;
};

export type LlmOutput = { type: "text" } | { type: "json"; schema: Record<string, unknown> };

export type StepKnowledge = {
  collection_ids?: string[];
  website_ids?: string[];
};

export type LlmStep = StepBase & {
  kind: "llm";
  prompt: string;
  input?: string;
  model_id?: string | null;
  model_kwargs?: Record<string, unknown> | null;
  files_from?: string[];
  knowledge?: StepKnowledge;
  output?: LlmOutput;
};

export type ComposeStep = StepBase & {
  kind: "compose";
  template: string;
};

export type DocumentFormat = "docx" | "pdf";

export type DocumentStep = StepBase & {
  kind: "document";
  format?: DocumentFormat;
  template_file_id?: string | null;
  title?: string | null;
  filename?: string | null;
  content?: string | null;
  values?: Record<string, string>;
};

export type ReviewMode = "view" | "edit";

export type ReviewStep = StepBase & {
  kind: "review";
  mode?: ReviewMode;
  of?: string | null;
  expires_after_seconds?: number | null;
};

export type SpeakerMapping = {
  participants_field?: string | null;
  infer_names?: boolean;
  model_id?: string | null;
};

export type TranscribeStep = StepBase & {
  kind: "transcribe";
  source: string;
  transcription_model_id?: string | null;
  language?: string | null;
  speaker_labels?: boolean;
  max_speakers?: number | null;
  speaker_mapping?: SpeakerMapping | null;
};

export type FlowStep = LlmStep | ComposeStep | DocumentStep | ReviewStep | TranscribeStep;

export type FlowDefinition = {
  schema_version?: number;
  form_fields: FormField[];
  steps: FlowStep[];
};

// --- Flows ------------------------------------------------------------------

export type FlowRunStatus =
  "queued" | "running" | "awaiting_review" | "completed" | "failed" | "cancelled";

export type StepResultStatus =
  "pending" | "running" | "awaiting_review" | "completed" | "failed" | "cancelled" | "skipped";

export type ReviewCheckpointState =
  "awaiting_review" | "edited" | "approved" | "rejected" | "resumed" | "cancelled" | "expired";

export type PrincipalType = "user" | "service";

export type FlowRunSummaryPublic = {
  id: string;
  flow_id: string;
  flow_version: number;
  tenant_id: string;
  principal_type: PrincipalType;
  status: FlowRunStatus;
  run_label?: string | null;
  job_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  cancelled_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type FlowSparsePublic = {
  id: string;
  space_id: string;
  name: string;
  description?: string | null;
  published_version?: number | null;
  step_count: number;
  step_kinds: StepKind[];
  conversation_id?: string | null;
  last_run?: FlowRunSummaryPublic | null;
  created_at: string;
  updated_at: string;
};

export type FlowPublic = {
  id: string;
  space_id: string;
  name: string;
  description?: string | null;
  definition: FlowDefinition;
  published_version?: number | null;
  has_unpublished_changes?: boolean;
  conversation_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type FlowAuthoringAssistantPublic = {
  assistant_id: string;
  space_id: string;
};

export type FlowRunContractPublic = {
  flow_id: string;
  published_flow_version: number;
  form_fields: FormField[];
  steps_requiring_review: { step_id: string; key: string; name: string; kind: StepKind }[];
  final_output?: { kind: StepKind; output_type: string } | null;
};

// --- Runs -------------------------------------------------------------------

export type FlowRunCreateRequest = {
  values?: Record<string, unknown>;
  files?: Record<string, string[]>;
  run_label?: string | null;
  expected_flow_version?: number | null;
};

export type FlowRunErrorPublic = { code: string; message: string };

export type FlowRunFilePublic = {
  id: string;
  name: string;
  mimetype?: string | null;
  size?: number | null;
  /** "input" | "output" */
  role: string;
  field_key?: string | null;
  step_id?: string | null;
};

export type FlowRunStepPublic = {
  step_id: string;
  key: string;
  name: string;
  kind: StepKind;
  step_order: number;
  status: StepResultStatus;
  current_attempt_no?: number;
  input_payload_json?: Record<string, unknown> | null;
  output_payload_json?: Record<string, unknown> | null;
  result_files?: FlowRunFilePublic[];
  num_tokens_input?: number | null;
  num_tokens_output?: number | null;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type FlowRunReviewCheckpointPublic = {
  id: string;
  flow_id: string;
  flow_run_id: string;
  step_id: string;
  step_order: number;
  attempt_no: number;
  state: ReviewCheckpointState;
  revision: number;
  /** "view" | "edit" */
  review_mode: string;
  /** "text" | "json" */
  output_type: string;
  original_payload_json?: Record<string, unknown> | null;
  current_payload_json?: Record<string, unknown> | null;
  requester_principal_type: PrincipalType;
  decided_by_principal_type?: PrincipalType | null;
  reason?: string | null;
  edited_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  resumed_at?: string | null;
  cancelled_at?: string | null;
  expires_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type FlowRunPublic = FlowRunSummaryPublic & {
  input_payload_json?: Record<string, unknown> | null;
  output_payload_json?: Record<string, unknown> | null;
  error?: FlowRunErrorPublic | null;
  input_files?: FlowRunFilePublic[];
  result_files?: FlowRunFilePublic[];
  steps?: FlowRunStepPublic[];
  review_checkpoint?: FlowRunReviewCheckpointPublic | null;
};

export type FlowRunReviewCheckpointResumeResponse = {
  checkpoint: FlowRunReviewCheckpointPublic;
  run: FlowRunSummaryPublic;
};

/** `PaginatedResponse[T]` from `eneo/main/models.py`: the items and their count. */
export type PaginatedResponse<T> = { items: T[]; count: number };

// --- Paths, in openapi-typescript's shape, for the typed fetch client -------

type Empty = Record<string, never>;
type JsonResponse<T> = { 200: { headers: Empty; content: { "application/json": T } } };
type Get<Path, Query, Result> = {
  parameters: { query?: Query; path: Path; header?: never; cookie?: never };
  requestBody?: never;
  responses: JsonResponse<Result>;
};
type GetByQuery<Query, Result> = {
  parameters: { query: Query; path?: never; header?: never; cookie?: never };
  requestBody?: never;
  responses: JsonResponse<Result>;
};
type Send<Path, Body, Result> = {
  parameters: { query?: never; path: Path; header?: never; cookie?: never };
  requestBody: { content: { "application/json": Body } };
  responses: JsonResponse<Result>;
};
type Post<Path, Result> = {
  parameters: { query?: never; path: Path; header?: never; cookie?: never };
  requestBody?: never;
  responses: JsonResponse<Result>;
};
type Delete<Path> = {
  parameters: { query?: never; path: Path; header?: never; cookie?: never };
  requestBody?: never;
  responses: { 204: { headers: Empty; content?: never } };
};

type FlowPath = { id: string };
type RunPath = { id: string; run_id: string };
type CheckpointPath = { id: string; run_id: string; checkpoint_id: string };
type RevisionBody = { expected_checkpoint_revision: number };

export type FlowPaths = {
  "/api/v1/flows/": {
    get: GetByQuery<{ space_id: string }, PaginatedResponse<FlowSparsePublic>>;
  };
  "/api/v1/flows/authoring-assistant/": {
    get: GetByQuery<{ space_id: string }, FlowAuthoringAssistantPublic>;
  };
  "/api/v1/flows/{id}/": {
    get: Get<FlowPath, never, FlowPublic>;
    delete: Delete<FlowPath>;
  };
  "/api/v1/flows/{id}/run-contract/": {
    get: Get<FlowPath, never, FlowRunContractPublic>;
  };
  "/api/v1/flows/{id}/runs/": {
    get: Get<
      FlowPath,
      { limit?: number; offset?: number },
      PaginatedResponse<FlowRunSummaryPublic>
    >;
    post: Send<FlowPath, FlowRunCreateRequest, FlowRunPublic>;
  };
  "/api/v1/flows/{id}/runs/{run_id}/": {
    get: Get<RunPath, never, FlowRunPublic>;
  };
  "/api/v1/flows/{id}/runs/{run_id}/cancel/": {
    post: Post<RunPath, FlowRunPublic>;
  };
  "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/": {
    patch: Send<
      CheckpointPath,
      RevisionBody & { current_payload_json: Record<string, unknown> },
      FlowRunReviewCheckpointPublic
    >;
  };
  "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/": {
    post: Send<CheckpointPath, RevisionBody, FlowRunReviewCheckpointResumeResponse>;
  };
  "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/": {
    post: Send<
      CheckpointPath,
      RevisionBody & { reason?: string | null },
      FlowRunReviewCheckpointPublic
    >;
  };
};
