import type { FlowRunRetentionPolicy } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { countMessage } from "./flowCount";

export const FLOW_RETENTION_MIN_DAYS = 1;
export const FLOW_RETENTION_MAX_DAYS = 2555;

/** A retention period in words: "30 dagar", and "1 dag" for one. */
export function retentionDays(days: number): string {
  return countMessage(days, m.flow_retention_days_count_one, m.flow_retention_days_count);
}

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
