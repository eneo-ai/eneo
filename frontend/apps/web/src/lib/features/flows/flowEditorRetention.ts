export const FLOW_RETENTION_MIN_DAYS = 1;
export const FLOW_RETENTION_MAX_DAYS = 2555;

export function isFlowRetentionDays(value: number): boolean {
  return (
    Number.isInteger(value) && value >= FLOW_RETENTION_MIN_DAYS && value <= FLOW_RETENTION_MAX_DAYS
  );
}

/**
 * Parse a retention-days text input: empty → null (no limit), a bare positive
 * integer → that number, anything else → undefined (reject, leave value as-is).
 */
export function parseFlowRetentionDaysInput(value: string): number | null | undefined {
  const rawValue = value.trim();
  if (rawValue === "") return null;
  if (!/^\d+$/.test(rawValue)) return undefined;
  return Number(rawValue);
}
