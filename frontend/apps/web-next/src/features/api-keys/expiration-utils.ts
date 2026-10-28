import type { ApiKey, ExpiringKeySummaryItem } from "./api-keys";

export type ExpiryLevel = "none" | "notice" | "warning" | "urgent" | "expired";

export type ExpiringKeyDisplayItem = {
  id: string;
  name: string;
  keySuffix: string | null;
  daysRemaining: number;
  level: ExpiryLevel;
  suspended: boolean;
};

export function getDaysUntilExpiration(value: string | null | undefined): number | null {
  if (!value) return null;
  return Math.floor((new Date(value).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

/** How close an expiry is, by the Svelte app's thresholds: 3, 14 and 30 days. */
export function getExpiryLevel(daysRemaining: number | null): ExpiryLevel {
  if (daysRemaining === null) return "none";
  if (daysRemaining < 0) return "expired";
  if (daysRemaining <= 3) return "urgent";
  if (daysRemaining <= 14) return "warning";
  if (daysRemaining <= 30) return "notice";
  return "none";
}

/** Among `keys`, how many have expired, expire within 3 days, and within 14 (not revoked ones). */
export function expiringCounts(keys: ApiKey[]): Record<"expired" | "urgent" | "warning", number> {
  const counts = { expired: 0, urgent: 0, warning: 0 };
  for (const key of keys) {
    if (key.revoked_at) continue;
    const level = getExpiryLevel(getDaysUntilExpiration(key.expires_at));
    if (level === "expired" || level === "urgent" || level === "warning") counts[level] += 1;
  }
  return counts;
}

export function summaryToDisplayItems(items: ExpiringKeySummaryItem[]): ExpiringKeyDisplayItem[] {
  return items.map((item) => ({
    id: item.id,
    name: item.name,
    keySuffix: item.key_suffix ?? null,
    daysRemaining: getDaysUntilExpiration(item.expires_at) ?? 0,
    level: item.severity,
    suspended: item.suspended_at != null
  }));
}
