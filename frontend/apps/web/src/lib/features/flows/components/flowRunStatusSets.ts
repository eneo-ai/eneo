import type { FlowRun } from "@intric/intric-js";

export type FlowRunStatus = FlowRun["status"];
export type FlowRunStatusFilter = FlowRunStatus | null;

export const FLOW_RUN_STATUS_FILTER_OPTIONS = [
  "completed",
  "failed",
  "running",
  "queued",
  "awaiting_review",
  "cancelled"
] as const satisfies readonly FlowRunStatus[];

const ACTIVE_FLOW_RUN_STATUS_VALUES = [
  "queued",
  "running"
] as const satisfies readonly FlowRunStatus[];
const TERMINAL_FLOW_RUN_STATUS_VALUES = [
  "completed",
  "failed",
  "cancelled"
] as const satisfies readonly FlowRunStatus[];
const CANCELLABLE_FLOW_RUN_STATUS_VALUES = [
  "queued",
  "running",
  "awaiting_review"
] as const satisfies readonly FlowRunStatus[];

const ACTIVE_FLOW_RUN_STATUSES: ReadonlySet<string> = new Set(ACTIVE_FLOW_RUN_STATUS_VALUES);
const TERMINAL_FLOW_RUN_STATUSES: ReadonlySet<string> = new Set(TERMINAL_FLOW_RUN_STATUS_VALUES);
const CANCELLABLE_FLOW_RUN_STATUSES: ReadonlySet<string> = new Set(
  CANCELLABLE_FLOW_RUN_STATUS_VALUES
);

export function isFlowRunActive(status: string): boolean {
  return ACTIVE_FLOW_RUN_STATUSES.has(status);
}

export function isFlowRunTerminal(status: string): boolean {
  return TERMINAL_FLOW_RUN_STATUSES.has(status);
}

export function isFlowRunCancellable(status: string): boolean {
  return CANCELLABLE_FLOW_RUN_STATUSES.has(status);
}

export function isFlowRunAwaitingReview(status: string): boolean {
  return status === "awaiting_review";
}

export function canRedispatchFlowRun(status: string): boolean {
  return status === "queued";
}
