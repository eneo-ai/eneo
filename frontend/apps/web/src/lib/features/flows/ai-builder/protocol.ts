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

type AIBuilderErrorEventData = Extract<AIBuilderParsedStreamEvent, { event: "error" }>["data"];

export function parseAIBuilderStreamEvent(
  rawEvent: AIBuilderStreamEvent
): AIBuilderParsedStreamEvent {
  switch (rawEvent.event) {
    case "text":
      return { event: "text", data: parseEventData<AIBuilderTextEventData>(rawEvent.data) };
    case "status":
      return { event: "status", data: parseEventData<AIBuilderStatusEventData>(rawEvent.data) };
    case "question":
      return { event: "question", data: parseEventData<AIBuilderQuestionEventData>(rawEvent.data) };
    case "requirements_summary":
      return {
        event: "requirements_summary",
        data: parseEventData<RequirementsSummary>(rawEvent.data)
      };
    case "plan":
      return { event: "plan", data: parseEventData<AIBuilderPlanStreamEventData>(rawEvent.data) };
    case "usage":
      return {
        event: "usage",
        data: parseTelemetryEventData(rawEvent.data)
      };
    case "error":
      return { event: "error", data: parseEventData<AIBuilderErrorEventData>(rawEvent.data) };
    case "done":
      if (rawEvent.data !== "") {
        throw new Error("AI Builder done event must have an empty data frame.");
      }
      return { event: "done", data: "" };
    default:
      throw new Error(`Unknown AI Builder stream event: ${rawEvent.event}`);
  }
}

function parseEventData<T>(data: string): T {
  return JSON.parse(data) as T;
}

function parseTelemetryEventData(data: string): AIBuilderUsageEventData {
  const parsed = parseEventData<GeneratedAIBuilderSessionTelemetrySummary>(data);
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
