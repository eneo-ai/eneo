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

export type StepChangeKind = "added" | "modified" | "removed" | "unchanged";

export interface StepChange {
  kind: StepChangeKind;
  step_name: string;
  step_ref: string | null;
  details: string | null;
}

export interface FlowEditDiff {
  step_changes: StepChange[];
  net_steps_added: number;
  net_steps_removed: number;
  flow_property_changes: Record<string, [unknown, unknown]>;
}

export type EditConfidence = "ready" | "needs_review" | "low_confidence";

export interface EditAdvisory {
  code: string;
  message: string;
  severity: "info" | "warning" | "error";
  field: string | null;
}

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

export type ApplyError =
  | {
      code: "stale_revision";
      message: string;
      context: Record<string, unknown>;
    }
  | {
      code: "flow_is_published";
      message: string;
      context: { flow_id?: string; published_version?: number } & Record<string, unknown>;
    }
  | {
      code: "invalid_existing_step_ref";
      message: string;
      context: Record<string, unknown>;
    }
  | {
      code: "transcription_model_required";
      message: string;
      context: Record<string, unknown>;
    }
  | {
      code: "flow_space_mismatch";
      message: string;
      context: Record<string, unknown>;
    }
  | {
      code: "insufficient_scope";
      message: string;
      context: Record<string, unknown>;
    }
  | {
      code: "not_found";
      message: string;
      context: Record<string, unknown>;
    }
  | {
      code: "flow_unpublished_apply_failed";
      message: string;
      context: {
        flow_id: string;
        original_code: ApplyError["code"];
        original_context: Record<string, unknown>;
      };
    }
  | {
      code: "network";
      message: string;
      context: { status: 0; stage?: string };
    }
  | {
      code: "unknown";
      message: string;
      context: {
        status?: number;
        original_code?: string;
        stage?: string;
      } & Record<string, unknown>;
    };

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

export interface AIBuilderErrorEventData {
  error: string;
  message: string;
  code: string;
  phase: string;
  request_id?: string | null;
}

export type AIBuilderQuestionEventData = StructuredQuestion;

// Required<> removes undefined from backend-defaulted counters; nullable last_* fields remain null-safe.
export type AIBuilderTelemetrySummary = Required<GeneratedAIBuilderSessionTelemetrySummary>;

export type AIBuilderUsageEventData = AIBuilderTelemetrySummary;
