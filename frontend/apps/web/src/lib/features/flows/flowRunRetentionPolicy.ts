import type { FlowRunRetentionPolicy } from "@eneo/eneo-js";

export const FLOW_RETENTION_MIN_DAYS = 1;
export const FLOW_RETENTION_MAX_DAYS = 2555;

export function parseFlowRunRetentionDays(value: string | number): number | null {
  const normalized = String(value).trim();
  if (!/^\d+$/.test(normalized)) return null;

  const days = Number(normalized);
  if (days < FLOW_RETENTION_MIN_DAYS || days > FLOW_RETENTION_MAX_DAYS) return null;
  return days;
}

export function flowRunRetentionPoliciesEqual(
  left: FlowRunRetentionPolicy | null,
  right: FlowRunRetentionPolicy | null
): boolean {
  if (left === null || right === null) return left === right;
  return left.mode === right.mode && left.days === right.days;
}
