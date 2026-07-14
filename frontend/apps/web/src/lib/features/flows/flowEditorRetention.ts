import type { FlowRunRetention } from "@eneo/eneo-js";

export const FLOW_RETENTION_MIN_DAYS = 1;
export const FLOW_RETENTION_MAX_DAYS = 2555;

export function isFlowRetentionDays(value: number): boolean {
  return (
    Number.isInteger(value) && value >= FLOW_RETENTION_MIN_DAYS && value <= FLOW_RETENTION_MAX_DAYS
  );
}

/**
 * Parse a retention-days text input: empty removes the Flow contribution, a
 * bare positive integer sets it, and anything else is rejected.
 */
export function parseFlowRetentionDaysInput(value: string): number | null | undefined {
  const rawValue = value.trim();
  if (rawValue === "") return null;
  if (!/^\d+$/.test(rawValue)) return undefined;
  return Number(rawValue);
}

export function canEditFlowRetentionContribution(
  retention: FlowRunRetention,
  published: boolean
): boolean {
  return !published && retention.state === "days";
}
