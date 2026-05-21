import type {
  AIBuilderDiagnosticContext,
  AIBuilderError,
  AIBuilderErrorDetails,
  AIBuilderErrorDetailValue,
  AIBuilderSession,
  AIBuilderTelemetrySummary,
  ProposedPlan,
  StepSpec
} from "./protocol";

export enum AIBuilderIssueKind {
  WrongStep = "wrong_step",
  MissingFormFields = "missing_form_fields",
  WrongOutputType = "wrong_output_type",
  UnclearQuestion = "unclear_question",
  BadEditResult = "bad_edit_result",
  Other = "other"
}

export type AIBuilderDiagnosticReportKind = "error" | "quality";
export type AIBuilderDiagnosticReportSurface =
  | "chat_stream"
  | "plan_apply"
  | "plan_quality"
  | "step_quality";

type DiagnosticStringField = Exclude<
  keyof AIBuilderDiagnosticContext,
  "error_code" | "error_category" | "error_phase"
>;

export type AIBuilderDiagnosticReportError = Pick<
  AIBuilderError,
  | "code"
  | "category"
  | "message"
  | "phase"
  | "request_id"
  | "intric_error_code"
  | "diagnostic_context"
  | "details"
>;

export type AIBuilderDiagnosticReportSessionSource = Pick<
  AIBuilderSession,
  "session_id" | "target_kind" | "flow_id" | "latest_plan_id" | "telemetry"
>;

export interface AIBuilderDiagnosticReportSession {
  session_id: string;
  target_kind: AIBuilderSession["target_kind"];
  flow_id?: string | null;
  latest_plan_id?: string | null;
  telemetry?: Pick<
    AIBuilderTelemetrySummary,
    "last_request_id" | "last_model" | "last_outcome_kind"
  > | null;
}

export type AIBuilderDiagnosticReportPlanSource = Pick<ProposedPlan, "plan_id" | "status">;

export interface AIBuilderDiagnosticReportPlan {
  plan_id: string;
  status?: ProposedPlan["status"] | null;
}

export type AIBuilderDiagnosticReportStepSource = Pick<
  StepSpec,
  "plan_step_ref" | "name" | "input_type" | "output_type"
>;

export interface AIBuilderDiagnosticReportStep {
  plan_step_ref: string;
  step_name?: string | null;
  step_number?: number | null;
  input_type?: string | null;
  output_type?: string | null;
}

export interface AIBuilderQualityIssueDetails {
  expected_output_type?: string | null;
  actual_output_type?: string | null;
  missing_form_field_count?: number | null;
  question_id?: string | null;
  lint_warning_count?: number | null;
  advisory_count?: number | null;
}

interface AIBuilderDiagnosticReportBaseInput {
  generated_at?: string;
  session?: AIBuilderDiagnosticReportSession | null;
  plan?: AIBuilderDiagnosticReportPlan | null;
}

export interface AIBuilderDiagnosticErrorReportInput extends AIBuilderDiagnosticReportBaseInput {
  kind: "error";
  surface: "chat_stream" | "plan_apply";
  error: AIBuilderDiagnosticReportError;
}

export interface AIBuilderPlanQualityReportInput extends AIBuilderDiagnosticReportBaseInput {
  kind: "quality";
  surface: "plan_quality";
  issue_kind: AIBuilderIssueKind;
  details?: AIBuilderQualityIssueDetails;
}

export interface AIBuilderStepQualityReportInput extends AIBuilderDiagnosticReportBaseInput {
  kind: "quality";
  surface: "step_quality";
  issue_kind: AIBuilderIssueKind;
  step: AIBuilderDiagnosticReportStep;
  details?: AIBuilderQualityIssueDetails;
}

export type AIBuilderDiagnosticReportInput =
  | AIBuilderDiagnosticErrorReportInput
  | AIBuilderPlanQualityReportInput
  | AIBuilderStepQualityReportInput;

export interface AIBuilderDiagnosticReportErrorSummary {
  code: string;
  category: AIBuilderError["category"];
  phase: AIBuilderError["phase"];
  message: string;
  request_id: string | null;
  intric_error_code?: number | null;
}

export interface AIBuilderDiagnosticReportContext {
  session_id: string | null;
  plan_id: string | null;
  request_id: string | null;
  request_id_source: "error" | "diagnostic_context" | "session_telemetry_last" | null;
  flow_id: string | null;
  target_kind: string | null;
  plan_step_ref: string | null;
  model: string | null;
  outcome_kind: string | null;
  plan_status: string | null;
  step_name: string | null;
  step_number: number | null;
  input_type: string | null;
  output_type: string | null;
}

export interface AIBuilderDiagnosticReport {
  schema_version: 1;
  report_kind: AIBuilderDiagnosticReportKind;
  surface: AIBuilderDiagnosticReportSurface;
  generated_at: string;
  issue_kind: AIBuilderIssueKind | null;
  error: AIBuilderDiagnosticReportErrorSummary | null;
  diagnostic_context: AIBuilderDiagnosticContext | null;
  details: AIBuilderErrorDetails;
  context: AIBuilderDiagnosticReportContext;
}

export function buildAIBuilderDiagnosticReportSession(
  session: AIBuilderDiagnosticReportSessionSource | null | undefined
): AIBuilderDiagnosticReportSession | null {
  if (!session) return null;
  return {
    session_id: session.session_id,
    target_kind: session.target_kind,
    flow_id: session.flow_id ?? null,
    latest_plan_id: session.latest_plan_id ?? null,
    telemetry: session.telemetry
      ? {
          last_request_id: session.telemetry.last_request_id ?? null,
          last_model: session.telemetry.last_model ?? null,
          last_outcome_kind: session.telemetry.last_outcome_kind ?? null
        }
      : null
  };
}

export function buildAIBuilderDiagnosticReportPlan(
  plan: AIBuilderDiagnosticReportPlanSource | null | undefined
): AIBuilderDiagnosticReportPlan | null {
  if (!plan) return null;
  return {
    plan_id: plan.plan_id,
    status: plan.status ?? null
  };
}

export function buildAIBuilderDiagnosticReportStep(
  step: AIBuilderDiagnosticReportStepSource,
  stepNumber?: number | null
): AIBuilderDiagnosticReportStep {
  return {
    plan_step_ref: step.plan_step_ref,
    step_name: step.name,
    step_number: stepNumber ?? null,
    input_type: step.input_type,
    output_type: step.output_type
  };
}

export function buildAIBuilderDiagnosticReport(
  input: AIBuilderDiagnosticReportInput
): AIBuilderDiagnosticReport {
  const diagnosticContext = buildDiagnosticContext(input);
  const context = buildReportContext(input, diagnosticContext);
  const error = input.kind === "error" ? buildErrorSummary(input.error) : null;

  return {
    schema_version: 1,
    report_kind: input.kind,
    surface: input.surface,
    generated_at: input.generated_at ?? new Date().toISOString(),
    issue_kind: input.kind === "quality" ? input.issue_kind : null,
    error,
    diagnostic_context: diagnosticContext,
    details: input.kind === "error" ? input.error.details : qualityDetails(input.details),
    context
  };
}

export function formatAIBuilderDiagnosticReport(report: AIBuilderDiagnosticReport): string {
  const lines = [
    "AI Builder diagnostic report",
    `schema_version: ${report.schema_version}`,
    `generated_at: ${report.generated_at}`,
    `report_kind: ${report.report_kind}`,
    `surface: ${report.surface}`
  ];

  if (report.issue_kind) {
    lines.push(`issue_kind: ${report.issue_kind}`);
  }

  if (report.error) {
    lines.push("", "error:");
    appendField(lines, "code", report.error.code);
    appendField(lines, "category", report.error.category);
    appendField(lines, "phase", report.error.phase);
    appendField(lines, "message", report.error.message);
    appendField(lines, "request_id", report.error.request_id);
    appendField(lines, "intric_error_code", report.error.intric_error_code);
  }

  lines.push("", "correlation:");
  appendField(lines, "session_id", report.context.session_id);
  appendField(lines, "plan_id", report.context.plan_id);
  appendField(lines, "request_id", report.context.request_id);
  appendField(lines, "request_id_source", report.context.request_id_source);
  appendField(lines, "flow_id", report.context.flow_id);
  appendField(lines, "target_kind", report.context.target_kind);
  appendField(lines, "plan_step_ref", report.context.plan_step_ref);
  appendField(lines, "model", report.context.model);
  appendField(lines, "outcome_kind", report.context.outcome_kind);
  appendField(lines, "plan_status", report.context.plan_status);
  appendField(lines, "step_name", report.context.step_name);
  appendField(lines, "step_number", report.context.step_number);
  appendField(lines, "input_type", report.context.input_type);
  appendField(lines, "output_type", report.context.output_type);

  const details = Object.entries(report.details).sort(([left], [right]) =>
    left.localeCompare(right)
  );
  if (details.length > 0) {
    lines.push("", "details:");
    for (const [key, value] of details) {
      appendField(lines, key, value);
    }
  }

  return `${lines.join("\n")}\n`;
}

function buildErrorSummary(
  error: AIBuilderDiagnosticReportError
): AIBuilderDiagnosticReportErrorSummary {
  return {
    code: error.code,
    category: error.category,
    phase: error.phase,
    message: error.message,
    request_id: error.request_id,
    intric_error_code: error.intric_error_code ?? null
  };
}

function buildDiagnosticContext(
  input: AIBuilderDiagnosticReportInput
): AIBuilderDiagnosticContext | null {
  const context: AIBuilderDiagnosticContext =
    input.kind === "error" && input.error.diagnostic_context
      ? { ...input.error.diagnostic_context }
      : {};
  const error = input.kind === "error" ? input.error : null;
  const session = input.session ?? null;
  const plan = input.plan ?? null;
  const step = input.kind === "quality" && input.surface === "step_quality" ? input.step : null;

  setDiagnosticStringField(context, "session_id", session?.session_id);
  setDiagnosticStringField(context, "plan_id", plan?.plan_id ?? session?.latest_plan_id);
  setDiagnosticStringField(
    context,
    "request_id",
    error?.request_id ?? session?.telemetry?.last_request_id
  );
  setDiagnosticStringField(context, "flow_id", session?.flow_id);
  setDiagnosticStringField(context, "target_kind", session?.target_kind);
  setDiagnosticStringField(context, "plan_step_ref", step?.plan_step_ref);
  setDiagnosticStringField(context, "model", session?.telemetry?.last_model);
  setDiagnosticStringField(context, "outcome_kind", session?.telemetry?.last_outcome_kind);

  return Object.keys(context).length > 0 ? context : null;
}

function buildReportContext(
  input: AIBuilderDiagnosticReportInput,
  diagnosticContext: AIBuilderDiagnosticContext | null
): AIBuilderDiagnosticReportContext {
  const error = input.kind === "error" ? input.error : null;
  const session = input.session ?? null;
  const plan = input.plan ?? null;
  const step = input.kind === "quality" && input.surface === "step_quality" ? input.step : null;
  const request = resolveRequestId(error, diagnosticContext, session);

  return {
    session_id: diagnosticContext?.session_id ?? session?.session_id ?? null,
    plan_id: diagnosticContext?.plan_id ?? plan?.plan_id ?? session?.latest_plan_id ?? null,
    request_id: request.value,
    request_id_source: request.source,
    flow_id: diagnosticContext?.flow_id ?? session?.flow_id ?? null,
    target_kind: diagnosticContext?.target_kind ?? session?.target_kind ?? null,
    plan_step_ref: diagnosticContext?.plan_step_ref ?? step?.plan_step_ref ?? null,
    model: diagnosticContext?.model ?? session?.telemetry?.last_model ?? null,
    outcome_kind: diagnosticContext?.outcome_kind ?? session?.telemetry?.last_outcome_kind ?? null,
    plan_status: plan?.status ?? null,
    step_name: step?.step_name ?? null,
    step_number: step?.step_number ?? null,
    input_type: step?.input_type ?? null,
    output_type: step?.output_type ?? null
  };
}

function resolveRequestId(
  error: AIBuilderDiagnosticReportError | null,
  diagnosticContext: AIBuilderDiagnosticContext | null,
  session: AIBuilderDiagnosticReportSession | null
): { value: string | null; source: AIBuilderDiagnosticReportContext["request_id_source"] } {
  if (error?.request_id) return { value: error.request_id, source: "error" };
  if (
    session?.telemetry?.last_request_id &&
    diagnosticContext?.request_id === session.telemetry.last_request_id
  ) {
    return { value: session.telemetry.last_request_id, source: "session_telemetry_last" };
  }
  if (diagnosticContext?.request_id) {
    return { value: diagnosticContext.request_id, source: "diagnostic_context" };
  }
  if (session?.telemetry?.last_request_id) {
    return { value: session.telemetry.last_request_id, source: "session_telemetry_last" };
  }
  return { value: null, source: null };
}

function setDiagnosticStringField(
  context: AIBuilderDiagnosticContext,
  key: DiagnosticStringField,
  value: string | null | undefined
): void {
  if (context[key] || !value) return;
  context[key] = value;
}

function qualityDetails(details: AIBuilderQualityIssueDetails | undefined): AIBuilderErrorDetails {
  const output: AIBuilderErrorDetails = {};
  if (!details) return output;

  assignDetail(output, "expected_output_type", details.expected_output_type);
  assignDetail(output, "actual_output_type", details.actual_output_type);
  assignDetail(output, "missing_form_field_count", details.missing_form_field_count);
  assignDetail(output, "question_id", details.question_id);
  assignDetail(output, "lint_warning_count", details.lint_warning_count);
  assignDetail(output, "advisory_count", details.advisory_count);
  return output;
}

function assignDetail(
  output: AIBuilderErrorDetails,
  key: string,
  value: AIBuilderErrorDetailValue | undefined
): void {
  if (value === undefined) return;
  if (typeof value === "number" && !Number.isFinite(value)) return;
  output[key] = value;
}

function appendField(
  lines: string[],
  label: string,
  value: string | number | boolean | null | undefined
): void {
  if (value === undefined || value === null || value === "") return;
  lines.push(`- ${label}: ${String(value)}`);
}
