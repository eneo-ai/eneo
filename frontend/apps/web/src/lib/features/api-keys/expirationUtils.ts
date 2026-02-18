import type { ApiKeyV2 } from "@intric/intric-js";

export type ExpiryLevel = "none" | "notice" | "warning" | "urgent" | "expired";

export interface ExpiringKeyInfo {
  key: ApiKeyV2;
  daysRemaining: number;
  level: ExpiryLevel;
}

/** Normalized display item used by the banner component. */
export interface ExpiringKeyDisplayItem {
  id: string;
  name: string;
  keySuffix: string | null;
  daysRemaining: number;
  level: ExpiryLevel;
  suspended: boolean;
}

// Threshold boundaries (days remaining)
const NOTICE_THRESHOLD = 30;
const WARNING_THRESHOLD = 14;
const URGENT_THRESHOLD = 3;

/**
 * Compute days until expiration using UTC-normalized math.
 * Returns null for missing dates. Negative values mean already expired.
 * Uses Math.floor so "expires in 3 minutes" → 0 (today), not 1 (tomorrow).
 */
export function getDaysUntilExpiration(date: string | null | undefined): number | null {
  if (!date) return null;
  const expiresAt = new Date(date).getTime();
  const now = Date.now();
  return Math.floor((expiresAt - now) / (1000 * 60 * 60 * 24));
}

/** Classify severity from days remaining. */
export function getExpiryLevel(daysRemaining: number | null): ExpiryLevel {
  if (daysRemaining === null) return "none";
  if (daysRemaining < 0) return "expired";
  if (daysRemaining <= URGENT_THRESHOLD) return "urgent";
  if (daysRemaining <= WARNING_THRESHOLD) return "warning";
  if (daysRemaining <= NOTICE_THRESHOLD) return "notice";
  return "none";
}

/**
 * Filter and classify non-revoked keys with expiration dates.
 * Sorted: expired first, then urgent, warning, notice — nearest expiry first within each tier.
 */
export function getExpiringKeys(keys: ApiKeyV2[]): ExpiringKeyInfo[] {
  const result: ExpiringKeyInfo[] = [];

  for (const key of keys) {
    if (key.revoked_at || !key.expires_at) continue;
    const days = getDaysUntilExpiration(key.expires_at);
    if (days === null) continue;
    const level = getExpiryLevel(days);
    if (level === "none") continue;
    result.push({ key, daysRemaining: days, level });
  }

  const tierOrder: Record<ExpiryLevel, number> = {
    expired: 0,
    urgent: 1,
    warning: 2,
    notice: 3,
    none: 4
  };

  result.sort((a, b) => {
    const tierDiff = tierOrder[a.level] - tierOrder[b.level];
    if (tierDiff !== 0) return tierDiff;
    return a.daysRemaining - b.daysRemaining;
  });

  return result;
}

/** Convert in-view keys to display items for the banner. */
export function toDisplayItems(expiringKeys: ExpiringKeyInfo[]): ExpiringKeyDisplayItem[] {
  return expiringKeys.map((ek) => ({
    id: ek.key.id,
    name: ek.key.name,
    keySuffix: ek.key.key_suffix ?? null,
    daysRemaining: ek.daysRemaining,
    level: ek.level,
    suspended: ek.key.suspended_at != null
  }));
}

/**
 * Compute effective state for display, overriding backend state when
 * expires_at has passed (backend state depends on async maintenance job).
 */
export function getEffectiveState(key: { state: string; expires_at?: string | null }): string {
  if (key.state === "revoked") return "revoked";
  if (key.expires_at) {
    if (Date.now() >= new Date(key.expires_at).getTime()) return "expired";
  }
  return key.state;
}

/** Convert endpoint summary items to display items for the banner. */
export function summaryToDisplayItems(
  items: Array<{
    id: string;
    name: string;
    key_suffix: string | null;
    expires_at: string;
    suspended_at: string | null;
    severity: string;
  }>
): ExpiringKeyDisplayItem[] {
  return items.map((item) => ({
    id: item.id,
    name: item.name,
    keySuffix: item.key_suffix,
    daysRemaining: getDaysUntilExpiration(item.expires_at) ?? 0,
    level: item.severity as ExpiryLevel,
    suspended: item.suspended_at != null
  }));
}
