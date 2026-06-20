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
} from "@intric/intric-js";
import type { StructuredQuestion } from "./structuredQuestionAnswer";

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

export type AIBuilderPlanEditScope = "whole_plan" | "step";

export interface AIBuilderPlanEditContext {
  scope: AIBuilderPlanEditScope;
  plan_id: string;
  target_plan_step_ref?: string | null;
  target_existing_step_ref?: string | null;
  target_step_name?: string | null;
  target_step_number?: number | null;
}

export interface AIBuilderSuggestChangeIntent {
  placeholder?: string;
  prefill?: string;
  editContext?: AIBuilderPlanEditContext | null;
}

export interface AIBuilderConversationToolCall {
  id?: string | null;
  name?: string | null;
  arguments?: Record<string, unknown> | null;
}

export type AIBuilderConversationMessage = Omit<
  GeneratedAIBuilderConversationMessage,
  "role" | "tool_calls"
> & {
  role: "user" | "assistant" | "tool" | "system";
  tool_calls?: AIBuilderConversationToolCall[] | null;
};

export type AIBuilderAttachmentFile = GeneratedAIBuilderAttachmentFile;

export type AIBuilderSession = Omit<
  GeneratedAIBuilderSessionResponse,
  "conversation" | "telemetry"
> & {
  telemetry?: AIBuilderTelemetrySummary | null;
  conversation?: AIBuilderConversationMessage[];
};

export type AIBuilderDraftSession = GeneratedAIBuilderDraftSession;

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
  Partial<GeneratedPlanHttpFields> & {
    edit_diff?: FlowEditDiff | null;
    edit_confidence?: EditConfidence | null;
    edit_warnings?: string[] | null;
    edit_advisories?: EditAdvisory[] | null;
    edit_risk_flags?: string[] | null;
  };

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
  intric_error_code?: number | null;
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

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  plan?: ProposedPlan;
  question?: StructuredQuestion;
  requirementsSummary?: RequirementsSummary;
  metadata?: Record<string, unknown>;
  timestamp: number;
}

export type AIBuilderModel = GeneratedAIBuilderModel;

export type AIBuilderTextEventData = Extract<AIBuilderParsedStreamEvent, { event: "text" }>["data"];

export type AIBuilderStatusEventData = Extract<
  AIBuilderParsedStreamEvent,
  { event: "status" }
>["data"];

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
