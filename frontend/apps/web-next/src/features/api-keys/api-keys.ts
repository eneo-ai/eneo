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
export function invalidateApiKeys(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: API_KEYS_KEY });
  void queryClient.invalidateQueries({ queryKey: ADMIN_API_KEYS_KEY });
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

/** A space, assistant or app a key can be scoped to. */
export type ScopeResource = { id: string; name: string; spaceName?: string };
export type ResourceScopeType = Exclude<ApiKeyScopeType, "tenant">;
export type ScopeResources = Record<ResourceScopeType, ScopeResource[]>;

/**
 * The spaces, assistants and apps the user can scope a key to, as the Svelte
 * app lists them: the user's spaces (the personal and the organization's
 * included), and each space's assistants and apps, published or not. A space
 * whose applications cannot be read keeps the published ones the list holds.
 */
export function apiKeyScopeResourcesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["api-key-scope-resources"],
    queryFn: async (): Promise<ScopeResources> => {
      const listed = await unwrap(
        api.GET("/api/v1/spaces/", {
          params: { query: { include_personal: true, include_applications: true } }
        })
      );
      const spaces = listed.items.map(({ id, name, applications }) => ({ id, name, applications }));
      const organization = await unwrap(api.GET("/api/v1/spaces/type/organization/")).catch(
        () => null
      );
      if (organization && !spaces.some((space) => space.id === organization.id)) {
        spaces.push({ id: organization.id, name: organization.name, applications: null });
      }
      const applications = await Promise.all(
        spaces.map((space) =>
          unwrap(
            api.GET("/api/v1/spaces/{id}/applications/", { params: { path: { id: space.id } } })
          ).catch(() => space.applications ?? null)
        )
      );
      return {
        space: spaces.map(({ id, name }) => ({ id, name })),
        assistant: spaces.flatMap((space, index) =>
          (applications[index]?.assistants.items ?? []).map(({ id, name }) => ({
            id,
            name,
            spaceName: space.name
          }))
        ),
        app: spaces.flatMap((space, index) =>
          (applications[index]?.apps.items ?? []).map(({ id, name }) => ({
            id,
            name,
            spaceName: space.name
          }))
        )
      };
    }
  });
}
