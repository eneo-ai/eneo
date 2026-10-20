import type { StatusTone } from "@/components/composites/status-label";
import type { FlowRunStatus, StepKind, StepResultStatus } from "./types";

type Translate = (key: string, values?: Record<string, string | number>) => string;

const KIND_KEYS: Record<StepKind, string> = {
  llm: "flow_step_kind_llm",
  compose: "flow_step_kind_compose",
  document: "flow_step_kind_document",
  review: "flow_step_kind_review",
  transcribe: "flow_step_kind_transcribe"
};

/** The human name of a step kind ("Modell", "Granskning"); an unknown kind shows as it is. */
export function stepKindLabel(kind: string, t: Translate): string {
  const key = KIND_KEYS[kind as StepKind];
  return key ? t(key) : kind;
}

const RUN_STATUS_KEYS: Record<FlowRunStatus, string> = {
  queued: "flow_run_status_queued",
  running: "flow_run_status_running",
  awaiting_review: "flow_run_status_awaiting_review",
  completed: "flow_run_status_completed",
  failed: "flow_run_status_failed",
  cancelled: "flow_run_status_cancelled"
};

export function runStatusLabel(status: string, t: Translate): string {
  const key = RUN_STATUS_KEYS[status as FlowRunStatus];
  return key ? t(key) : status;
}

/** The colour of a run's status; colour never carries the meaning alone (the label does). */
export function runStatusTone(status: FlowRunStatus | string): StatusTone {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "awaiting_review":
      return "warning";
    case "running":
    case "queued":
      return "accent";
    default:
      return "neutral";
  }
}

const STEP_STATUS_KEYS: Record<StepResultStatus, string> = {
  pending: "flow_step_status_pending",
  running: "flow_step_status_running",
  awaiting_review: "flow_step_status_awaiting_review",
  completed: "flow_step_status_completed",
  failed: "flow_step_status_failed",
  cancelled: "flow_step_status_cancelled",
  skipped: "flow_step_status_skipped"
};

export function stepStatusLabel(status: string, t: Translate): string {
  const key = STEP_STATUS_KEYS[status as StepResultStatus];
  return key ? t(key) : status;
}

/** A short identifier for a run: its label, else the first characters of its id. */
export function runDisplayName(run: { id: string; run_label?: string | null }): string {
  return run.run_label?.trim() || `#${run.id.slice(0, 8)}`;
}

/** "7 dagar", "3 timmar", "45 minuter": a review's time limit. */
export function formatDuration(seconds: number, t: Translate): string {
  if (seconds % 86_400 === 0) return t("flow_duration_days", { count: seconds / 86_400 });
  if (seconds % 3_600 === 0) return t("flow_duration_hours", { count: seconds / 3_600 });
  return t("flow_duration_minutes", { count: Math.max(1, Math.round(seconds / 60)) });
}
