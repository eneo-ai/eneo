import type { components } from "@intric/intric-js";
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

export type TargetKind = "create" | "edit";

export type SessionStatus = "chatting" | "awaiting_approval" | "applying" | "applied" | "cancelled";

export type PlanStatus = "proposed" | "approved" | "applied" | "rejected" | "superseded";

export interface AIBuilderConversationToolCall {
  id?: string | null;
  name?: string | null;
  arguments?: Record<string, unknown> | null;
}

export interface AIBuilderConversationMessage {
  role: "user" | "assistant" | "tool" | "system";
  content?: string | null;
  timestamp?: string | null;
  tool_calls?: AIBuilderConversationToolCall[] | null;
  tool_call_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface AIBuilderAttachmentFile {
  id: string;
  name: string;
  mimetype: string;
  size: number;
  transcription?: string | null;
  token_count?: number | null;
}

export interface AIBuilderSession {
  session_id: string;
  status: SessionStatus;
  target_kind: TargetKind;
  flow_id: string | null;
  latest_plan_id: string | null;
  telemetry?: AIBuilderTelemetrySummary | null;
  conversation?: AIBuilderConversationMessage[];
  attachments?: AIBuilderAttachmentFile[];
  attachment_warnings?: string[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AIBuilderDraftSession extends AIBuilderSession {
  space_id: string;
  draft_title: string | null;
}

export interface StepSpec {
  plan_step_ref: string;
  existing_step_ref: string | null;
  name: string;
  assistant_spec: {
    instructions: string;
    model_ref: string | null;
    knowledge_refs: string[];
    mcp_server_refs?: string[];
    mcp_tool_refs?: string[];
  };
  input_source: string;
  input_type: string;
  output_mode: string;
  output_type: string;
  input_bindings: Record<string, unknown> | null;
  input_contract: Record<string, unknown> | null;
  output_contract: Record<string, unknown> | null;
  input_config: Record<string, unknown> | null;
  output_config: Record<string, unknown> | null;
}

export interface FlowDraftSpecCore {
  flow_name: string;
  flow_description: string;
  steps: StepSpec[];
  form_fields: Array<{
    name: string;
    type: string;
    label: string;
    required: boolean;
    options: string[] | null;
  }> | null;
}

export interface LintWarning {
  step_ref: string | null;
  code: string;
  message: string;
  severity: "warning" | "info";
}

export interface PlannerPlanEnvelope {
  spec: FlowDraftSpecCore;
  assumptions: string[];
  lint_warnings: LintWarning[];
  risk_acknowledgments: string[];
  plan_rationale?: string | null;
}

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

export interface ProposedPlan {
  plan_id: string;
  status: PlanStatus;
  envelope: PlannerPlanEnvelope;
  edit_diff?: FlowEditDiff | null;
  edit_confidence?: EditConfidence | null;
  edit_warnings?: string[] | null;
  edit_advisories?: EditAdvisory[] | null;
  edit_risk_flags?: string[] | null;
}

export interface ApplyError {
  code: string;
  message: string;
  context: Record<string, unknown>;
}

export type PlanRevisionType = "keep_current_description";

export interface ApplyResult {
  flow_id: string;
  flow_name: string;
  steps_created: number;
  steps_updated: number;
  steps_removed: number;
}

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

export interface AIBuilderModel {
  id: string;
  name: string;
  provider: string;
}

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

export type AIBuilderTelemetrySummary = Required<components["schemas"]["SessionTelemetrySummary"]>;

export type AIBuilderUsageEventData = AIBuilderTelemetrySummary;
