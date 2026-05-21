import type {
  AIBuilderApplyResult as GeneratedAIBuilderApplyResult,
  AIBuilderAttachmentFile as GeneratedAIBuilderAttachmentFile,
  AIBuilderConversationMessage as GeneratedAIBuilderConversationMessage,
  AIBuilderDraftSession as GeneratedAIBuilderDraftSession,
  AIBuilderFlowDraftSpecCore as GeneratedAIBuilderFlowDraftSpecCore,
  AIBuilderLintWarning as GeneratedAIBuilderLintWarning,
  AIBuilderModel as GeneratedAIBuilderModel,
  AIBuilderPlanResponse as GeneratedAIBuilderPlanResponse,
  AIBuilderPlannerPlanEnvelope as GeneratedAIBuilderPlannerPlanEnvelope,
  AIBuilderSessionResponse as GeneratedAIBuilderSessionResponse,
  AIBuilderSessionTelemetrySummary as GeneratedAIBuilderSessionTelemetrySummary,
  AIBuilderStepSpec as GeneratedAIBuilderStepSpec,
  components
} from "@intric/intric-js";
import type { StructuredQuestion } from "./structuredQuestionAnswer";

export type AIBuilderEventType =
  | "text"
  | "plan"
  | "question"
  | "requirements_summary"
  | "usage"
  | "error"
  | "status"
  | "done";

export interface AIBuilderStreamEvent {
  event: AIBuilderEventType;
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

export type PlannerPlanEnvelope = GeneratedAIBuilderPlannerPlanEnvelope;

export type BuilderPlanEditResult = components["schemas"]["BuilderPlanEditResult"];

export type CompiledEditResult = components["schemas"]["CompiledEditResult"];

export type StepChange = components["schemas"]["StepChange"];

export type StepChangeKind = StepChange["kind"];

export type FlowEditDiff = components["schemas"]["FlowEditDiff"];

export type EditConfidence = NonNullable<CompiledEditResult["confidence"]>;

export type EditAdvisory = components["schemas"]["EditAdvisory"];

export type AIBuilderPlanEventData = components["schemas"]["AIBuilderPlanEventData"];

type GeneratedPlanHttpFields = Pick<
  GeneratedAIBuilderPlanResponse,
  "session_id" | "spec_hash" | "created_at" | "updated_at" | "edit_result_json"
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

export type AIBuilderErrorContextValue = string | number | boolean | null;

export type AIBuilderErrorContext = Record<string, AIBuilderErrorContextValue>;

export interface AIBuilderError {
  schema_version: 1;
  code: string;
  category: AIBuilderErrorCategory;
  message: string;
  phase: AIBuilderErrorPhase;
  request_id: string | null;
  intric_error_code?: number | null;
  context: AIBuilderErrorContext;
}

export type ApplyError = AIBuilderError;

export type PlanRevisionType = components["schemas"]["RevisePlanRequest"]["type"];

export type ApplyResult = GeneratedAIBuilderApplyResult;

export interface KeyDecision {
  topic: string;
  decision: string;
}

export interface RequirementsSummary {
  requirements_version?: string | null;
  summary: string;
  key_decisions: KeyDecision[];
  input_description: string;
  output_description: string;
  assumptions?: string[];
  manual_setup_notes?: string[];
}

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

export interface AIBuilderTextEventData {
  text: string;
}

export interface AIBuilderStatusEventData {
  status: string;
}

export type AIBuilderQuestionEventData = StructuredQuestion;

// Required<> removes undefined from backend-defaulted counters; nullable last_* fields remain null-safe.
export type AIBuilderTelemetrySummary = Required<GeneratedAIBuilderSessionTelemetrySummary>;

export type AIBuilderUsageEventData = AIBuilderTelemetrySummary;
