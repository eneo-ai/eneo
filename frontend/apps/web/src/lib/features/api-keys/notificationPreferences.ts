import type { ApiKeyScopeType, Eneo } from "@eneo/eneo-js";

export type ApiKeyNotificationTargetType = "key" | "assistant" | "app" | "space";

export interface ApiKeyNotificationPreferences {
  enabled: boolean;
  days_before_expiry: number[];
  auto_follow_published_assistants: boolean;
  auto_follow_published_apps: boolean;
}

export interface ApiKeyNotificationPolicy {
  enabled: boolean;
  default_days_before_expiry: number[];
  max_days_before_expiry: number | null;
  allow_auto_follow_published_assistants: boolean;
  allow_auto_follow_published_apps: boolean;
}

export interface ApiKeyNotificationSubscription {
  target_type: ApiKeyNotificationTargetType;
  target_id: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object";
}

function normalizeDayValues(raw: unknown): number[] {
  if (!Array.isArray(raw)) return [];
  return Array.from(
    new Set(
      raw
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value) && value > 0)
        .map((value) => Math.floor(value))
    )
  ).sort((a, b) => b - a);
}

export function normalizePreferences(raw: unknown): ApiKeyNotificationPreferences {
  const data = isObject(raw) ? raw : {};
  const days = normalizeDayValues(data.days_before_expiry);
  return {
    enabled: Boolean(data.enabled),
    days_before_expiry: days.length > 0 ? days : [30],
    auto_follow_published_assistants: Boolean(data.auto_follow_published_assistants),
    auto_follow_published_apps: Boolean(data.auto_follow_published_apps)
  };
}

export function normalizePolicy(raw: unknown): ApiKeyNotificationPolicy {
  const data = isObject(raw) ? raw : {};
  const defaultDays = normalizeDayValues(data.default_days_before_expiry);
  const parsedMax = Number(data.max_days_before_expiry);
  return {
    enabled: data.enabled !== false,
    default_days_before_expiry: defaultDays.length > 0 ? defaultDays : [30],
    max_days_before_expiry:
      Number.isFinite(parsedMax) && parsedMax > 0 ? Math.floor(parsedMax) : null,
    allow_auto_follow_published_assistants: Boolean(data.allow_auto_follow_published_assistants),
    allow_auto_follow_published_apps: Boolean(data.allow_auto_follow_published_apps)
  };
}

function normalizeSubscription(raw: unknown): ApiKeyNotificationSubscription | null {
  if (!isObject(raw)) return null;
  const targetType = raw.target_type;
  const targetId = raw.target_id;
  if (
    (targetType === "key" ||
      targetType === "assistant" ||
      targetType === "app" ||
      targetType === "space") &&
    typeof targetId === "string" &&
    targetId.length > 0
  ) {
    return {
      target_type: targetType,
      target_id: targetId
    };
  }
  return null;
}

function mapScopeTypeToTargetType(
  scopeType: ApiKeyScopeType | string
): ApiKeyNotificationTargetType {
  const normalized = String(scopeType).toLowerCase();
  if (normalized === "assistant") return "assistant";
  if (normalized === "app") return "app";
  if (normalized === "space") return "space";
  throw new Error(`scope_not_followable:${scopeType}`);
}

export function extractFollowedKeyIds(
  subscriptions: ApiKeyNotificationSubscription[]
): Set<string> {
  return new Set(
    subscriptions
      .filter((subscription) => subscription.target_type === "key")
      .map((subscription) => subscription.target_id)
  );
}

export function hasScopeSubscription(
  subscriptions: ApiKeyNotificationSubscription[],
  scopeType: ApiKeyScopeType | string,
  scopeId: string
): boolean {
  const targetType = mapScopeTypeToTargetType(scopeType);
  return subscriptions.some(
    (subscription) => subscription.target_type === targetType && subscription.target_id === scopeId
  );
}

export async function getNotificationPreferences(
  eneo: Eneo
): Promise<ApiKeyNotificationPreferences> {
  const response = await eneo.apiKeys.getNotificationPreferences();
  return normalizePreferences(response);
}

export async function updateNotificationPreferences(
  eneo: Eneo,
  updates: Partial<ApiKeyNotificationPreferences>
): Promise<ApiKeyNotificationPreferences> {
  const response = await eneo.apiKeys.updateNotificationPreferences(updates);
  return normalizePreferences(response);
}

export async function listNotificationSubscriptions(
  eneo: Eneo
): Promise<ApiKeyNotificationSubscription[]> {
  const response = await eneo.apiKeys.listNotificationSubscriptions();
  const rawItems = isObject(response) && Array.isArray(response.items) ? response.items : [];
  return rawItems
    .map((item) => normalizeSubscription(item))
    .filter((item): item is ApiKeyNotificationSubscription => item !== null);
}

export async function followApiKeyNotifications(eneo: Eneo, apiKeyId: string): Promise<void> {
  await eneo.apiKeys.followNotificationTarget({
    target_type: "key",
    target_id: apiKeyId
  });
}

export async function unfollowApiKeyNotifications(eneo: Eneo, apiKeyId: string): Promise<void> {
  await eneo.apiKeys.unfollowNotificationTarget({
    target_type: "key",
    target_id: apiKeyId
  });
}

export async function followScopeNotifications(
  eneo: Eneo,
  scopeType: ApiKeyScopeType | string,
  scopeId: string
): Promise<void> {
  await eneo.apiKeys.followNotificationTarget({
    target_type: mapScopeTypeToTargetType(scopeType),
    target_id: scopeId
  });
}

export async function unfollowScopeNotifications(
  eneo: Eneo,
  scopeType: ApiKeyScopeType | string,
  scopeId: string
): Promise<void> {
  await eneo.apiKeys.unfollowNotificationTarget({
    target_type: mapScopeTypeToTargetType(scopeType),
    target_id: scopeId
  });
}

export async function getAdminNotificationPolicy(eneo: Eneo): Promise<ApiKeyNotificationPolicy> {
  const response = await eneo.apiKeys.admin.getNotificationPolicy();
  return normalizePolicy(response);
}

export async function updateAdminNotificationPolicy(
  eneo: Eneo,
  updates: Partial<ApiKeyNotificationPolicy>
): Promise<ApiKeyNotificationPolicy> {
  const response = await eneo.apiKeys.admin.updateNotificationPolicy(updates);
  return normalizePolicy(response);
}
