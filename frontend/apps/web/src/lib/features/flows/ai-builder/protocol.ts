import type {
  AIBuilderApplyResult as GeneratedAIBuilderApplyResult,
  AIBuilderAttachmentFile as GeneratedAIBuilderAttachmentFile,
  AIBuilderConversationMessage as GeneratedAIBuilderConversationMessage,
  AIBuilderDraftSession as GeneratedAIBuilderDraftSession,
  AIBuilderFlowDraftSpecCore as GeneratedAIBuilderFlowDraftSpecCore,
  AIBuilderLintWarning as GeneratedAIBuilderLintWarning,
  AIBuilderModel as GeneratedAIBuilderModel,
  AIBuilderPlanResponse as GeneratedAIBuilderPlanResponse,
  AIBuilderSessionResponse as GeneratedAIBuilderSessionResponse,
  AIBuilderSessionTelemetrySummary as GeneratedAIBuilderSessionTelemetrySummary,
  AIBuilderStepSpec as GeneratedAIBuilderStepSpec,
  components,
  operations
} from "@eneo/eneo-js";
import { z } from "zod";
import type {
  PersistedStructuredQuestionAnswerMetadata,
  StructuredQuestion
} from "./structuredQuestionAnswer";

type SendAIBuilderMessageOperation = operations["send_ai_builder_message"];
type GeneratedAIBuilderParsedStreamEvent =
  SendAIBuilderMessageOperation["responses"][200]["content"]["text/event-stream"];
// Required<> removes undefined from backend-defaulted counters; nullable last_* fields remain null-safe.
export type AIBuilderTelemetrySummary = Required<GeneratedAIBuilderSessionTelemetrySummary>;
export type AIBuilderUsageEventData = AIBuilderTelemetrySummary;
export type AIBuilderParsedStreamEvent =
  | Exclude<GeneratedAIBuilderParsedStreamEvent, { event: "usage" }>
  | { event: "usage"; data: AIBuilderUsageEventData };
export type AIBuilderEventType = AIBuilderParsedStreamEvent["event"];

export interface AIBuilderStreamEvent {
  event: AIBuilderEventType | string;
  data: string;
}

export type TargetKind = components["schemas"]["TargetKind"];

export type SessionStatus = components["schemas"]["SessionStatus"];

export type PlanStatus = components["schemas"]["PlanStatus"];

export type AIBuilderSendMessageRequest = components["schemas"]["SendMessageRequest"];

export type AIBuilderTurnState = components["schemas"]["BuilderTurnState"];

export type AIBuilderTurnRecoveryState = Extract<
  AIBuilderTurnState,
  "failed_before_provider" | "provider_outcome_unknown"
>;

export type AIBuilderPlanEditContext = NonNullable<AIBuilderSendMessageRequest["edit_context"]>;

export type AIBuilderPlanEditScope = AIBuilderPlanEditContext["scope"];

export interface AIBuilderSuggestChangeIntent {
  placeholder?: string;
  prefill?: string;
  editContext?: AIBuilderPlanEditContext | null;
}

export type AIBuilderConversationMessage = GeneratedAIBuilderConversationMessage;

export type AIBuilderAttachmentFile = GeneratedAIBuilderAttachmentFile;

export type AIBuilderSession = Omit<GeneratedAIBuilderSessionResponse, "telemetry"> & {
  telemetry?: AIBuilderTelemetrySummary | null;
};

export type AIBuilderDraftSession = GeneratedAIBuilderDraftSession;

export type AIBuilderSessionListResponse = components["schemas"]["SessionListResponse"];

export type RecoverableAIBuilderDraftSession = AIBuilderDraftSession & {
  status: Extract<SessionStatus, "chatting" | "awaiting_approval">;
};

function isRecoverableDraftStatus(
  status: SessionStatus
): status is RecoverableAIBuilderDraftSession["status"] {
  switch (status) {
    case "chatting":
    case "awaiting_approval":
      return true;
    case "applied":
    case "cancelled":
      return false;
  }
  const unhandledStatus: never = status;
  throw new Error(`Unhandled AI Builder session status: ${unhandledStatus}`);
}

/** Shared by the builder's recovery flow and the flows page's resume strip so
 *  both surfaces agree on what counts as an in-progress create draft. */
export function isRecoverableCreateDraft(
  session: AIBuilderDraftSession,
  spaceId: string
): session is RecoverableAIBuilderDraftSession {
  return (
    session.space_id === spaceId &&
    session.target_kind === "create" &&
    session.flow_id === null &&
    isRecoverableDraftStatus(session.status)
  );
}

export type StepSpec = GeneratedAIBuilderStepSpec;

export type FlowDraftSpecCore = GeneratedAIBuilderFlowDraftSpecCore;

export type LintWarning = GeneratedAIBuilderLintWarning;

export type FlowBuilderProposalContent = components["schemas"]["FlowBuilderProposalContent"];

export type FlowBuilderEditApproval = components["schemas"]["FlowBuilderEditApproval"];

export type StepChange = components["schemas"]["StepChange"];

export type StepChangeKind = StepChange["kind"];

export type FlowEditDiff = components["schemas"]["FlowEditDiff"];

export type EditConfidence = NonNullable<FlowBuilderEditApproval["confidence"]>;

export type EditAdvisory = components["schemas"]["EditAdvisory"];

export type AIBuilderPlanEventData = components["schemas"]["AIBuilderPlanEventData"];

type GeneratedPlanHttpFields = Pick<
  GeneratedAIBuilderPlanResponse,
  "session_id" | "spec_hash" | "created_at" | "updated_at"
>;

export type ProposedPlan = Omit<GeneratedAIBuilderPlanResponse, keyof GeneratedPlanHttpFields> &
  Partial<GeneratedPlanHttpFields>;

export type IncomingProposedPlan = Omit<ProposedPlan, "status"> & { status?: PlanStatus };

export type AIBuilderErrorCategory =
  | "bad_request"
  | "conflict"
  | "internal"
  | "network"
  | "not_found"
  | "soft_block"
  | "unauthorized"
  | "upstream";

export type AIBuilderErrorPhase =
  | "client"
  | "planner"
  | "proposal"
  | "question"
  | "question_recovery"
  | "requirements"
  | "router"
  | "self_correction";

export type AIBuilderDiagnosticContext = components["schemas"]["AIBuilderDiagnosticContext"];

export type AIBuilderErrorDetailValue = string | number | boolean | null;

export type AIBuilderErrorDetails = Record<string, AIBuilderErrorDetailValue>;

// Parsed UI error is a superset of generated AIBuilderPublicError: the client
// synthesizes the "client" phase and "network" category for local failures.
export interface AIBuilderError {
  schema_version: 2;
  code: string;
  category: AIBuilderErrorCategory;
  message: string;
  phase: AIBuilderErrorPhase;
  request_id: string | null;
  eneo_error_code?: number | null;
  diagnostic_context: AIBuilderDiagnosticContext | null;
  details: AIBuilderErrorDetails;
}

export type ApplyError = AIBuilderError;

export type PlanRevisionType = components["schemas"]["RevisePlanRequest"]["type"];

export type ApplyResult = GeneratedAIBuilderApplyResult;

export type RequirementsSummary = Extract<
  AIBuilderParsedStreamEvent,
  { event: "requirements_summary" }
>["data"];

export type AIBuilderPhase = "discovering" | "confirming" | "building" | "reviewing";

/** Truthful outcome of a send: the composer may only discard its draft on
 *  "delivered" — every other edge keeps the user's text (state diagram §4). */
export type AIBuilderSendOutcome = "delivered" | "failed" | "not_started";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  plan?: ProposedPlan;
  question?: StructuredQuestion;
  requirementsSummary?: RequirementsSummary;
  /** Typed structured-question answer carried by a user message; set at the
   *  hydration/optimistic boundary so views never parse metadata dicts. */
  questionAnswer?: PersistedStructuredQuestionAnswerMetadata;
  metadata?: Record<string, unknown>;
  timestamp: number;
}

export type AIBuilderModel = GeneratedAIBuilderModel;

export type AIBuilderTextEventData = Extract<AIBuilderParsedStreamEvent, { event: "text" }>["data"];

export type AIBuilderStatusEventData = Extract<
  AIBuilderParsedStreamEvent,
  { event: "status" }
>["data"];

export type AIBuilderStatus = AIBuilderStatusEventData["status"];

export type AIBuilderQuestionEventData = Extract<
  AIBuilderParsedStreamEvent,
  { event: "question" }
>["data"];

type AIBuilderPlanStreamEventData = Extract<AIBuilderParsedStreamEvent, { event: "plan" }>["data"];

export type AIBuilderPublicErrorPayload = Extract<
  AIBuilderParsedStreamEvent,
  { event: "error" }
>["data"];

const jsonRecordSchema = z.record(z.string(), z.unknown());
const nullableJsonRecordSchema = jsonRecordSchema.nullable().optional();
const nullableStringSchema = z.string().nullable().optional();
const stringArraySchema = z.array(z.string());
const fieldProvenanceSchema = z.enum([
  "user_confirmed",
  "template_derived",
  "runtime_inferred",
  "model_proposed"
]);

// Public FlowStepReviewPolicy constraint; changing it requires the backend contract to change first.
const reviewExpirySecondsSchema = z
  .int()
  .min(60)
  .max(90 * 24 * 60 * 60);

const assistantSpecSchema = z.object({
  instructions: z.string(),
  model_ref: nullableStringSchema,
  knowledge_refs: stringArraySchema.optional()
});

const reviewPolicySchema = z.strictObject({
  mode: z.enum(["view", "edit"]),
  expires_after_seconds: reviewExpirySecondsSchema.nullable().optional()
});

const stepSpecSchema = z.object({
  plan_step_ref: z.string(),
  existing_step_ref: nullableStringSchema,
  name: z.string(),
  assistant_spec: assistantSpecSchema,
  input_source: z.enum(["flow_input", "previous_step", "all_previous_steps"]),
  input_type: z.enum(["text", "json", "audio", "document", "file", "any"]).optional(),
  output_mode: z
    .enum(["pass_through", "compose_text", "transcribe_only", "template_fill", "render_verbatim"])
    .optional(),
  output_type: z.enum(["text", "json", "pdf", "docx"]).optional(),
  input_bindings: nullableJsonRecordSchema,
  input_contract: nullableJsonRecordSchema,
  output_contract: nullableJsonRecordSchema,
  input_config: nullableJsonRecordSchema,
  output_config: nullableJsonRecordSchema,
  review_policy: reviewPolicySchema.nullable().optional()
});

const formFieldSpecSchema = z.object({
  name: z.string(),
  type: z.string(),
  label: z.string(),
  required: z.boolean().optional(),
  options: stringArraySchema.nullable().optional()
});

const flowDraftSpecSchema = z.object({
  flow_name: z.string(),
  flow_description: z.string().optional(),
  steps: z.array(stepSpecSchema),
  form_fields: z.array(formFieldSpecSchema).nullable().optional(),
  document_body_writer_step_refs: stringArraySchema.nullable().optional()
});

const lintWarningSchema = z.object({
  step_ref: nullableStringSchema,
  code: z.string(),
  message: z.string(),
  severity: z.enum(["warning", "info"]).optional(),
  field_name: nullableStringSchema,
  field_provenance: fieldProvenanceSchema.nullable().optional()
});

const editAdvisorySchema = z.object({
  code: z.string(),
  message: z.string(),
  severity: z.enum(["info", "warning", "error"]),
  field: nullableStringSchema,
  field_provenance: fieldProvenanceSchema.nullable().optional()
});

const stepChangeSchema = z.object({
  kind: z.enum(["added", "modified", "removed", "unchanged"]),
  step_name: z.string(),
  step_ref: nullableStringSchema,
  details: nullableStringSchema
});

const formFieldChangeSchema = z.object({
  kind: z.enum(["added", "modified", "removed"]),
  field_name: z.string(),
  details: nullableStringSchema
});

const metadataChangeSchema = z.object({
  kind: z.enum(["added", "modified", "removed"]),
  path: z.string(),
  old_value: z.unknown().optional(),
  new_value: z.unknown().optional()
});

const flowEditDiffSchema = z.object({
  step_changes: z.array(stepChangeSchema),
  form_changes: z.array(formFieldChangeSchema).optional(),
  metadata_changes: z.array(metadataChangeSchema).optional(),
  flow_property_changes: z.record(z.string(), z.tuple([z.unknown(), z.unknown()])).optional(),
  net_steps_added: z.int().optional(),
  net_steps_removed: z.int().optional()
});

const flowBuilderEditApprovalSchema = z.strictObject({
  base_flow_revision: z.int(),
  removed_existing_step_refs: stringArraySchema.optional(),
  diff: flowEditDiffSchema,
  warnings: stringArraySchema.optional(),
  advisories: z.array(editAdvisorySchema).optional(),
  risk_flags: stringArraySchema.optional(),
  confidence: z.enum(["ready", "needs_review", "low_confidence"]).optional()
});

const mappedStepUpperBoundSchema = z.strictObject({
  plan_step_ref: z.string(),
  execution_mode: z.enum(["per_source", "per_item"]),
  maximum_items: z.int().min(1)
});

const executionShapeSchema = z.strictObject({
  completion_model_step_count: z.int().nonnegative(),
  transcription_model_step_count: z.int().nonnegative(),
  deterministic_step_count: z.int().nonnegative(),
  schema_constrained_step_count: z.int().nonnegative(),
  mapped_step_upper_bounds: z.array(mappedStepUpperBoundSchema).optional()
});

const flowBuilderProposalSchema = z.strictObject({
  spec: flowDraftSpecSchema,
  assumptions: stringArraySchema.optional(),
  lint_warnings: z.array(lintWarningSchema).optional(),
  plan_rationale: nullableStringSchema,
  description_override_manual: z.boolean().optional(),
  edit: flowBuilderEditApprovalSchema.nullable().optional(),
  execution_shape: executionShapeSchema
});

const textEventDataSchema = z.object({
  text: z.string()
}) satisfies z.ZodType<AIBuilderTextEventData>;

const statusEventDataSchema = z.object({
  status: z.enum(["architecture_committed", "architecture_revised", "repairing"])
}) satisfies z.ZodType<AIBuilderStatusEventData>;

const questionOptionSchema = z.object({
  id: nullableStringSchema,
  label: z.string(),
  value: z.union([z.string(), z.number(), z.boolean(), z.null()]).optional(),
  description: nullableStringSchema
});

const questionEventDataSchema = z.object({
  question_id: z.string(),
  question: z.string(),
  options: z.array(questionOptionSchema),
  selection_mode: z.enum(["single", "multi"]),
  allow_custom: z.boolean(),
  requires_confirm: z.boolean().optional(),
  input_field_collection: z.boolean().optional()
}) satisfies z.ZodType<AIBuilderQuestionEventData>;

const requirementsSummaryEventDataSchema = z.object({
  requirements_version: nullableStringSchema,
  summary: z.string(),
  key_decisions: z.array(
    z.object({
      topic: z.string(),
      decision: z.string()
    })
  ),
  input_description: z.string(),
  output_description: z.string(),
  assumptions: stringArraySchema.optional(),
  manual_setup_notes: stringArraySchema.optional()
}) satisfies z.ZodType<RequirementsSummary>;

const planEventDataSchema = z.strictObject({
  plan_id: z.uuid(),
  proposal: flowBuilderProposalSchema
}) satisfies z.ZodType<AIBuilderPlanStreamEventData>;

const telemetryEventDataSchema = z.object({
  planner_request_count: z.int().optional(),
  clarification_question_count: z.int().optional(),
  prompt_tokens_total: z.int().optional(),
  completion_tokens_total: z.int().optional(),
  total_tokens_total: z.int().optional(),
  tool_call_count_total: z.int().optional(),
  auxiliary_llm_call_count: z.int().optional(),
  architecture_commit_count: z.int().optional(),
  repair_attempts_total: z.int().optional(),
  parse_repair_attempts_total: z.int().optional(),
  wall_clock_ms_total: z.int().optional(),
  llm_calls_made_total: z.int().optional(),
  token_usage_estimated: z.boolean().optional(),
  last_request_id: nullableStringSchema,
  last_model: nullableStringSchema,
  last_finish_reason: nullableStringSchema,
  last_outcome_kind: nullableStringSchema,
  last_token_usage_source: nullableStringSchema,
  last_token_usage_estimated: z.boolean().optional()
}) satisfies z.ZodType<GeneratedAIBuilderSessionTelemetrySummary>;

const aiBuilderErrorCodes = [
  "architecture_critic_invariant_failed",
  "architecture_materialization_failed",
  "ai_builder_plan_resource_binding_unavailable",
  "ai_builder_plan_resource_bindings_missing",
  "bad_request",
  "builder_attachment_unavailable",
  "edit_session_flow_required",
  "flow_is_published",
  "flow_space_mismatch",
  "invalid_ai_builder_settings",
  "insufficient_scope",
  "insufficient_space_permission",
  "invalid_existing_step_ref",
  "invalid_plan_step_ref",
  "invalid_plan_status",
  "invalid_question_payload",
  "invalid_session_transition",
  "model_not_available",
  "not_found",
  "no_planner_model_available",
  "output_schema_limit_exceeded",
  "plan_not_proposed",
  "plan_session_mismatch",
  "planning_state_payload_too_large",
  "planning_state_version_mismatch",
  "planner_budget_missing",
  "planner_model_missing_context_window",
  "planner_model_missing_output_tokens",
  "planner_context_limit_exceeded",
  "planner_invalid_repair_response",
  "planner_output_too_long",
  "planner_parse_error",
  "planner_rejected",
  "planner_stream_failed",
  "planner_upstream_error",
  "proposal_tool_missing",
  "question_recovery_exhausted",
  "question_recovery_unavailable",
  "requirements_incomplete",
  "requirements_not_confirmed",
  "self_correction_invalid_payload",
  "self_correction_invalid_plan",
  "self_correction_quality_failure",
  "session_creator_required",
  "session_message_in_progress",
  "session_latest_plan_update_conflict",
  "session_send_in_progress",
  "session_send_lease_lost",
  "session_turn_idempotency_conflict",
  "session_turn_provider_outcome_unknown",
  "stale_plan_revision",
  "stale_revision",
  "transcription_model_required",
  "unsupported_revision_type"
] as const satisfies readonly AIBuilderPublicErrorPayload["code"][];
const eneoErrorCodes = [
  9000, 9001, 9002, 9003, 9004, 9005, 9006, 9007, 9008, 9009, 9010, 9011, 9012, 9013, 9014, 9015,
  9016, 9017, 9018, 9019, 9020, 9021, 9022, 9023, 9024, 9025, 9026, 9027, 9028, 9029, 9030, 9031,
  9032, 9033, 9034, 9035, 9036, 9037, 9038, 9039, 9040, 9041, 9042, 9043
] as const satisfies readonly AIBuilderPublicErrorPayload["eneo_error_code"][];
const errorCategories = [
  "bad_request",
  "conflict",
  "internal",
  "not_found",
  "soft_block",
  "unauthorized",
  "upstream"
] as const satisfies readonly AIBuilderPublicErrorPayload["category"][];
const errorPhases = [
  "planner",
  "proposal",
  "question",
  "question_recovery",
  "requirements",
  "router",
  "self_correction"
] as const satisfies readonly AIBuilderPublicErrorPayload["phase"][];

type AssertNever<T extends never> = T;
type _MissingAIBuilderErrorCode = AssertNever<
  Exclude<AIBuilderPublicErrorPayload["code"], (typeof aiBuilderErrorCodes)[number]>
>;
type _MissingEneoErrorCode = AssertNever<
  Exclude<AIBuilderPublicErrorPayload["eneo_error_code"], (typeof eneoErrorCodes)[number]>
>;
type _MissingAIBuilderErrorCategory = AssertNever<
  Exclude<AIBuilderPublicErrorPayload["category"], (typeof errorCategories)[number]>
>;
type _MissingAIBuilderErrorPhase = AssertNever<
  Exclude<AIBuilderPublicErrorPayload["phase"], (typeof errorPhases)[number]>
>;

const errorCodeSchema = z.enum(aiBuilderErrorCodes);
const eneoErrorCodeSchema = z.literal(eneoErrorCodes);
const errorCategorySchema = z.enum(errorCategories);
const errorPhaseSchema = z.enum(errorPhases);
const errorDiagnosticContextSchema = z.strictObject({
  session_id: nullableStringSchema,
  plan_id: nullableStringSchema,
  request_id: nullableStringSchema,
  flow_id: nullableStringSchema,
  space_id: nullableStringSchema,
  target_kind: nullableStringSchema,
  plan_step_ref: nullableStringSchema,
  error_code: errorCodeSchema.nullable().optional(),
  error_category: errorCategorySchema.nullable().optional(),
  error_phase: errorPhaseSchema.nullable().optional(),
  model: nullableStringSchema,
  outcome_kind: nullableStringSchema
});
const errorDetailValueSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);
const errorEventDataSchema = z.strictObject({
  schema_version: z.literal(2).optional(),
  code: errorCodeSchema,
  category: errorCategorySchema,
  message: z.string().min(1),
  phase: errorPhaseSchema,
  eneo_error_code: eneoErrorCodeSchema,
  request_id: z.string().min(1),
  diagnostic_context: errorDiagnosticContextSchema.nullable().optional(),
  details: z.record(z.string(), errorDetailValueSchema).nullable().optional()
}) satisfies z.ZodType<AIBuilderPublicErrorPayload>;

// A generated event addition must gain a runtime schema in the same change.
const eventDataSchemas = {
  text: textEventDataSchema,
  status: statusEventDataSchema,
  question: questionEventDataSchema,
  requirements_summary: requirementsSummaryEventDataSchema,
  plan: planEventDataSchema,
  usage: telemetryEventDataSchema,
  error: errorEventDataSchema
} satisfies Record<Exclude<AIBuilderEventType, "done">, z.ZodType>;

type GeneratedEventDataByName = {
  [
    Event in Exclude<GeneratedAIBuilderParsedStreamEvent, { event: "done" }> as Event["event"]
  ]: Event["data"];
};
type RuntimeEventDataByName = {
  [EventName in keyof typeof eventDataSchemas]: z.output<(typeof eventDataSchemas)[EventName]>;
};
type DeepMutable<Value> = Value extends object
  ? { -readonly [Key in keyof Value]: DeepMutable<Value[Key]> }
  : Value;
type IsExactType<Left, Right> =
  (<Value>() => Value extends DeepMutable<Left> ? 1 : 2) extends <
    Value
  >() => Value extends DeepMutable<Right> ? 1 : 2
    ? (<Value>() => Value extends DeepMutable<Right> ? 1 : 2) extends <
        Value
      >() => Value extends DeepMutable<Left> ? 1 : 2
      ? true
      : false
    : false;
type AssertTrue<T extends true> = T;
type AssertFalse<T extends false> = T;
type _ExactTypeRejectsAddedOptionalField = AssertFalse<
  IsExactType<{ required: string }, { required: string; added?: number }>
>;
type _ExactTypePreservesTupleArity = AssertFalse<IsExactType<[string, string], string[]>>;
type _RuntimeEventSchemasMatchGeneratedContract = AssertTrue<
  IsExactType<RuntimeEventDataByName, GeneratedEventDataByName>
>;

export function parseAIBuilderPublicErrorPayload(
  payload: unknown
): AIBuilderPublicErrorPayload | null {
  const result = errorEventDataSchema.safeParse(payload);
  return result.success ? result.data : null;
}

export function parseAIBuilderStreamEvent(
  rawEvent: AIBuilderStreamEvent
): AIBuilderParsedStreamEvent {
  switch (rawEvent.event) {
    case "text":
      return { event: "text", data: parseEventData("text", rawEvent.data, eventDataSchemas.text) };
    case "status":
      return {
        event: "status",
        data: parseEventData("status", rawEvent.data, eventDataSchemas.status)
      };
    case "question":
      return {
        event: "question",
        data: parseEventData("question", rawEvent.data, eventDataSchemas.question)
      };
    case "requirements_summary":
      return {
        event: "requirements_summary",
        data: parseEventData(
          "requirements_summary",
          rawEvent.data,
          eventDataSchemas.requirements_summary
        )
      };
    case "plan":
      return {
        event: "plan",
        data: parseEventData("plan", rawEvent.data, eventDataSchemas.plan)
      };
    case "usage":
      return {
        event: "usage",
        data: parseTelemetryEventData(rawEvent.data)
      };
    case "error":
      return {
        event: "error",
        data: parseEventData("error", rawEvent.data, eventDataSchemas.error)
      };
    case "done":
      if (rawEvent.data !== "") {
        throw new Error("AI Builder done event must have an empty data frame.");
      }
      return { event: "done", data: "" };
    default:
      throw new Error(`Unknown AI Builder stream event: ${rawEvent.event}`);
  }
}

function parseEventData<T>(event: string, data: string, schema: z.ZodType<T>): T {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data) as unknown;
  } catch (cause) {
    throw new Error(`Invalid AI Builder ${event} event payload: malformed JSON.`, { cause });
  }
  const result = schema.safeParse(parsed);
  if (!result.success) {
    const issue = result.error.issues[0];
    const location = issue?.path.length ? ` at ${issue.path.map(String).join(".")}` : "";
    throw new Error(
      `Invalid AI Builder ${event} event payload${location}: ${issue?.message ?? "schema mismatch"}.`
    );
  }
  return result.data;
}

function parseTelemetryEventData(data: string): AIBuilderUsageEventData {
  const parsed = parseEventData("usage", data, eventDataSchemas.usage);
  return {
    planner_request_count: parsed.planner_request_count ?? 0,
    clarification_question_count: parsed.clarification_question_count ?? 0,
    prompt_tokens_total: parsed.prompt_tokens_total ?? 0,
    completion_tokens_total: parsed.completion_tokens_total ?? 0,
    total_tokens_total: parsed.total_tokens_total ?? 0,
    tool_call_count_total: parsed.tool_call_count_total ?? 0,
    auxiliary_llm_call_count: parsed.auxiliary_llm_call_count ?? 0,
    architecture_commit_count: parsed.architecture_commit_count ?? 0,
    repair_attempts_total: parsed.repair_attempts_total ?? 0,
    parse_repair_attempts_total: parsed.parse_repair_attempts_total ?? 0,
    wall_clock_ms_total: parsed.wall_clock_ms_total ?? 0,
    llm_calls_made_total: parsed.llm_calls_made_total ?? 0,
    token_usage_estimated: parsed.token_usage_estimated ?? false,
    last_request_id: parsed.last_request_id ?? null,
    last_model: parsed.last_model ?? null,
    last_finish_reason: parsed.last_finish_reason ?? null,
    last_outcome_kind: parsed.last_outcome_kind ?? null,
    last_token_usage_source: parsed.last_token_usage_source ?? null,
    last_token_usage_estimated: parsed.last_token_usage_estimated ?? false
  };
}
