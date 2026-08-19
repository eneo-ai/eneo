export const FLOW_RETENTION_MIN_DAYS = 1;
export const FLOW_RETENTION_MAX_DAYS = 2555;

export type FlowRetentionDaysParseResult =
  { ok: true; days: number | null } | { ok: false; reason: "integer" | "out_of_range" };

export function parseFlowRetentionDays(value: string): FlowRetentionDaysParseResult {
  const normalized = value.trim();
  if (normalized === "") return { ok: true, days: null };

  const days = Number(normalized);
  if (!Number.isInteger(days)) return { ok: false, reason: "integer" };
  if (days < FLOW_RETENTION_MIN_DAYS || days > FLOW_RETENTION_MAX_DAYS) {
    return { ok: false, reason: "out_of_range" };
  }
  return { ok: true, days };
}

export function retentionDaysChangeIsDestructive(
  currentDays: number | null,
  proposedDays: number | null
): boolean {
  return proposedDays !== null && (currentDays === null || proposedDays < currentDays);
}

export function formatFlowRetentionBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
}
