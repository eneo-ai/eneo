import type { Schema } from "@/lib/api/models";

export type ApiKey = Schema<"ApiKeyV2">;
export type ApiKeyCreateRequest = Schema<"ApiKeyCreateRequest">;
export type ApiKeyOwnership = Schema<"ApiKeyOwnership">;
export type ApiKeyPermission = Schema<"ApiKeyPermission">;
export type ApiKeyScopeType = Schema<"ApiKeyScopeType">;
export type ApiKeyState = Schema<"ApiKeyState">;
export type ApiKeyType = Schema<"ApiKeyType">;
export type ExpiringKeySummaryItem = Schema<"ExpiringKeySummaryItem">;
export type ExpiringKeysSummary = Schema<"ExpiringKeysSummary">;

export const API_KEY_STATES: ApiKeyState[] = ["active", "suspended", "revoked", "expired"];

export const API_KEY_STATE_BADGE_VARIANT: Record<
  ApiKeyState,
  "default" | "secondary" | "destructive" | "outline"
> = {
  active: "default",
  suspended: "secondary",
  revoked: "destructive",
  expired: "outline"
};

// Radix Select items need non-empty values; "never" encodes no expiration.
export const API_KEY_EXPIRY_PRESETS = [
  { key: "api_keys_exp_no_expiration", value: "never" },
  { key: "api_keys_exp_30_days", value: "30" },
  { key: "api_keys_exp_90_days", value: "90" },
  { key: "api_keys_exp_1_year", value: "365" }
] as const;

export type ApiKeyExpiryPresetValue = (typeof API_KEY_EXPIRY_PRESETS)[number]["value"];

export function formatApiKeyDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

export function apiKeyExpiresAt(expiryDays: ApiKeyExpiryPresetValue): string | null {
  if (expiryDays === "never") return null;
  const days = Number(expiryDays);
  return new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
}

export function buildTenantApiKeyCreateBody({
  name,
  ownership,
  permission,
  expiryDays
}: {
  name: string;
  ownership: ApiKeyOwnership;
  permission: ApiKeyPermission;
  expiryDays: ApiKeyExpiryPresetValue;
}): ApiKeyCreateRequest {
  return {
    name: name.trim(),
    key_type: "sk_",
    permission,
    scope_type: "tenant",
    ownership,
    expires_at: apiKeyExpiresAt(expiryDays)
  };
}

export function buildScopedApiKeyCreateBody({
  name,
  scopeType,
  scopeId,
  permission,
  expiryDays
}: {
  name: string;
  scopeType: Extract<ApiKeyScopeType, "space" | "assistant" | "app">;
  scopeId: string;
  permission: ApiKeyPermission;
  expiryDays: ApiKeyExpiryPresetValue;
}): ApiKeyCreateRequest {
  return {
    name: name.trim(),
    key_type: "sk_",
    permission,
    scope_type: scopeType,
    scope_id: scopeId,
    ownership: "user",
    expires_at: apiKeyExpiresAt(expiryDays)
  };
}
