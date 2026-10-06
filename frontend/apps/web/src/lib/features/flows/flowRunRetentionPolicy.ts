import type { FlowRunRetentionPolicy, FlowRunRetentionPolicySettings } from "@eneo/eneo-js";

export const FLOW_RETENTION_MIN_DAYS = 1;
// The fixed range of the debug-evidence and upload windows; run-history rules
// use the deployment maximum the API reports (write_rules.max_days).
export const FLOW_RETENTION_MAX_DAYS = 2555;

export function parseFlowRunRetentionDays(
  value: string | number,
  max: number = FLOW_RETENTION_MAX_DAYS
): number | null {
  const normalized = String(value).trim();
  if (!/^\d+$/.test(normalized)) return null;

  const days = Number(normalized);
  if (days < FLOW_RETENTION_MIN_DAYS || days > max) return null;
  return days;
}

export function flowRunRetentionPoliciesEqual(
  left: FlowRunRetentionPolicy | null,
  right: FlowRunRetentionPolicy | null
): boolean {
  if (left === null || right === null) return left === right;
  return left.mode === right.mode && left.days === right.days;
}

/** The policy in force at a level: its own, else the one it inherits. */
export function effectiveFlowRunRetentionPolicy(
  settings: FlowRunRetentionPolicySettings,
  local: FlowRunRetentionPolicy | null = settings.local_policy
): FlowRunRetentionPolicy | null {
  return local ?? settings.inherited_policy;
}

/**
 * Mirrors the API rule (flow_run_retention_change_postpones_deletion): a change
 * that stops or delays automatic deletion needs a reason. The API decides; this
 * only shows the reason field before the first attempt.
 */
export function flowRunRetentionChangePostponesDeletion(
  before: FlowRunRetentionPolicy | null,
  after: FlowRunRetentionPolicy | null
): boolean {
  if (before === null || before.mode !== "auto_delete") return false;
  return after === null || after.mode !== "auto_delete" || after.days > before.days;
}
