import { queryOptions, type QueryClient } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type ApiKey = Schema<"ApiKeyV2">;
export type ApiKeyCreateRequest = Schema<"ApiKeyCreateRequest">;
export type ApiKeyCreatedResponse = Schema<"ApiKeyCreatedResponse">;
export type ApiKeyUpdateRequest = Schema<"ApiKeyUpdateRequest">;
export type ApiKeyCreationConstraints = Schema<"ApiKeyCreationConstraints">;
export type ApiKeyOwnership = Schema<"ApiKeyOwnership">;
export type ApiKeyPermission = Schema<"ApiKeyPermission">;
export type ApiKeyScopeType = Schema<"ApiKeyScopeType">;
export type ApiKeyState = Schema<"ApiKeyState">;
export type ApiKeyType = Schema<"ApiKeyType">;
export type ResourcePermissionLevel = Schema<"ResourcePermissionLevel">;
export type ExpiringKeySummaryItem = Schema<"ExpiringKeySummaryItem">;
export type ExpiringKeysSummary = Schema<"ExpiringKeysSummary">;

export const API_KEY_STATES: ApiKeyState[] = ["active", "suspended", "revoked", "expired"];

/** The state tabs over a key list: every key, or those in one state. */
export type ApiKeyStateFilter = ApiKeyState | "all";
export const API_KEY_STATE_FILTERS: ApiKeyStateFilter[] = ["all", ...API_KEY_STATES];

/** The message key naming a state tab. */
export function stateFilterLabelKey(filter: ApiKeyStateFilter): string {
  return filter === "all" ? "api_keys_admin_state_all" : `api_keys_status_${filter}`;
}

export const API_KEY_STATE_BADGE_VARIANT: Record<
  ApiKeyState,
  "default" | "secondary" | "destructive" | "outline"
> = {
  active: "default",
  suspended: "secondary",
  revoked: "destructive",
  expired: "outline"
};

export function formatApiKeyDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

/** Every list of the user's keys (the account's, a resource's, the expiring ones). */
export const API_KEYS_KEY = ["api-keys"] as const;
/** The organization's keys on the admin page. */
export const ADMIN_API_KEYS_KEY = ["admin-api-keys"] as const;

/**
 * After a key changes, every list that may show it: an admin's change can
 * touch their own keys and a user's can touch the organization's list.
 */
export function invalidateApiKeys(queryClient: QueryClient): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: API_KEYS_KEY }),
    queryClient.invalidateQueries({ queryKey: ADMIN_API_KEYS_KEY })
  ]);
}

/** The keys, assistants, apps and spaces whose expiring keys the user is reminded of. */
export const API_KEY_SUBSCRIPTIONS_KEY = ["api-key-notification-subscriptions"] as const;

/**
 * The shell's expiring-keys bell reads again, what the user follows included:
 * a follow changed, or publishing an assistant or app (auto-follow) added one.
 */
export function invalidateExpiringApiKeys(queryClient: QueryClient): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: API_KEY_SUBSCRIPTIONS_KEY }),
    queryClient.invalidateQueries({ queryKey: [...API_KEYS_KEY, "expiring-soon"] })
  ]);
}

export const API_KEY_POLICY_CONSTRAINTS_KEY = ["api-key-policy-constraints"] as const;

/**
 * The tenant policy as it bounds a new key, a rotation or an expiry change:
 * required expiry, the longest expiry, the highest rate limit and the
 * rotation grace period. The forms only show these; the backend enforces them.
 */
export function apiKeyPolicyConstraintsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: API_KEY_POLICY_CONSTRAINTS_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/api-keys/policy-constraints"))
  });
}

/**
 * A created or rotated key without its secret. The secret goes to `reveal`
 * (the one-time dialog) and never into React Query's cache, where a
 * mutation's result would otherwise stay after the dialog has closed.
 */
export async function withoutSecret(
  request: Promise<ApiKeyCreatedResponse>,
  reveal: (secret: string) => void
): Promise<ApiKey> {
  const { api_key, secret } = await request;
  reveal(secret);
  return api_key;
}

export type ResourceScopeType = Exclude<ApiKeyScopeType, "tenant">;

/** Whose endpoints manage a key: its owner's (and their scope's), or an admin's for the tenant. */
export type ApiKeyMode = "user" | "admin";

/** A suspension's or revocation's optional reason, coded by who acts (as the Svelte app does). */
export function stateChangeRequest(mode: ApiKeyMode, reason: string) {
  return {
    reason_code: mode === "admin" ? ("admin_action" as const) : ("user_request" as const),
    reason_text: reason.trim() || null
  };
}

/*
 * One call per lifecycle action, sent to the user's or the admin's endpoint
 * (openapi-fetch needs each literal path).
 */

export function updateApiKey(
  api: EneoClient,
  mode: ApiKeyMode,
  id: string,
  body: ApiKeyUpdateRequest
) {
  const params = { path: { id } };
  return mode === "admin"
    ? unwrap(api.PATCH("/api/v1/admin/api-keys/{id}", { params, body }))
    : unwrap(api.PATCH("/api/v1/api-keys/{id}", { params, body }));
}

export function rotateApiKey(
  api: EneoClient,
  mode: ApiKeyMode,
  id: string,
  body: Schema<"ApiKeyRotateRequest">
): Promise<ApiKeyCreatedResponse> {
  const params = { path: { id } };
  return mode === "admin"
    ? unwrap(api.POST("/api/v1/admin/api-keys/{id}/rotate", { params, body }))
    : unwrap(api.POST("/api/v1/api-keys/{id}/rotate", { params, body }));
}

export function extendApiKey(
  api: EneoClient,
  mode: ApiKeyMode,
  id: string,
  expiresAt: string | null
) {
  const params = { path: { id } };
  const body = { expires_at: expiresAt };
  return mode === "admin"
    ? unwrap(api.POST("/api/v1/admin/api-keys/{id}/extend", { params, body }))
    : unwrap(api.POST("/api/v1/api-keys/{id}/extend", { params, body }));
}

export function suspendApiKey(api: EneoClient, mode: ApiKeyMode, id: string, reason: string) {
  const params = { path: { id } };
  const body = stateChangeRequest(mode, reason);
  return mode === "admin"
    ? unwrap(api.POST("/api/v1/admin/api-keys/{id}/suspend", { params, body }))
    : unwrap(api.POST("/api/v1/api-keys/{id}/suspend", { params, body }));
}

export function revokeApiKey(api: EneoClient, mode: ApiKeyMode, id: string, reason: string) {
  const params = { path: { id } };
  const body = stateChangeRequest(mode, reason);
  return mode === "admin"
    ? unwrap(api.POST("/api/v1/admin/api-keys/{id}/revoke", { params, body }))
    : unwrap(api.POST("/api/v1/api-keys/{id}/revoke", { params, body }));
}

export function reactivateApiKey(api: EneoClient, mode: ApiKeyMode, id: string) {
  const params = { path: { id } };
  return mode === "admin"
    ? unwrap(api.POST("/api/v1/admin/api-keys/{id}/reactivate", { params }))
    : unwrap(api.POST("/api/v1/api-keys/{id}/reactivate", { params }));
}

/** Deletes a revoked or expired key for good. */
export function purgeApiKey(api: EneoClient, mode: ApiKeyMode, id: string) {
  const params = { path: { id } };
  return mode === "admin"
    ? unwrap(api.POST("/api/v1/admin/api-keys/{id}/purge", { params }))
    : unwrap(api.POST("/api/v1/api-keys/{id}/purge", { params }));
}

export function apiKeyUsagePage(
  api: EneoClient,
  mode: ApiKeyMode,
  id: string,
  cursor: string | undefined
) {
  const params = { path: { id }, query: { cursor, limit: 50 } };
  return mode === "admin"
    ? unwrap(api.GET("/api/v1/admin/api-keys/{id}/usage", { params }))
    : unwrap(api.GET("/api/v1/api-keys/{id}/usage", { params }));
}

/**
 * Whether the signed-in user may act on a key from their own pages: a personal
 * key only its owner, a service key anyone its scope admits (the backend
 * decides). An admin acts on every key of the tenant.
 */
export function canManageApiKey(key: ApiKey, mode: ApiKeyMode, userId: string): boolean {
  return mode === "admin" || key.ownership === "service" || key.owner_user_id === userId;
}
