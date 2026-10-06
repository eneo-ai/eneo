import type { ExpiringKeySummaryItem } from "./api-keys";

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
