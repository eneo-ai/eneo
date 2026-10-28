import type { ApiKeyScopeType, ApiKeyStateFilter, ApiKeyType } from "@/features/api-keys/api-keys";
import type { Schema } from "@/lib/api/models";

/** How the admin narrows the tenant's keys (the state is the page's tabs). */
export type AdminKeyFilters = {
  /** Name, suffix or description; a pasted full secret is looked up instead. */
  search: string;
  /** The owner's or creator's user id and e-mail. */
  user: { id: string; label: string } | null;
  userRelation: Schema<"ApiKeyUserRelation">;
  scopeType: ApiKeyScopeType | "all";
  /** A space, assistant or app of `scopeType`. */
  scopeId: string | null;
  keyType: ApiKeyType | "all";
  /** As typed; a whole number of days. */
  expiresWithinDays: string;
  limit: number;
};

export const RESULT_LIMITS = [25, 50, 100, 250];

export const DEFAULT_ADMIN_KEY_FILTERS: AdminKeyFilters = {
  search: "",
  user: null,
  userRelation: "owner",
  scopeType: "all",
  scopeId: null,
  keyType: "all",
  expiresWithinDays: "",
  limit: 100
};

/**
 * Whether the search is a whole key, to look up exactly (as the Svelte app
 * tells one): a known prefix, letters and digits, and at least 40 characters.
 */
export function isFullApiKeySecret(value: string): boolean {
  const secret = value.trim();
  return secret.length >= 40 && /^(sk_|pk_|inp_|ina_)[a-z0-9]+$/i.test(secret);
}

/**
 * A whole key that matched nothing is searched by its last 8 characters, the
 * suffix keys are stored with, so a mistyped or rotated key still finds its
 * candidates without the secret being sent as a search.
 */
export function secretSuffix(value: string): string {
  return value.trim().split("_", 2)[1]?.slice(-8) ?? "";
}

function positiveDays(value: string): number | undefined {
  const days = Math.floor(Number(value.trim()));
  return value.trim() && Number.isFinite(days) && days > 0 ? days : undefined;
}

/** The list request's query for applied filters, a state tab and a page. */
export function adminKeyListQuery(
  filters: AdminKeyFilters,
  state: ApiKeyStateFilter,
  cursor: string | undefined
) {
  const search = filters.search.trim();
  return {
    cursor,
    limit: filters.limit,
    state: state === "all" ? undefined : state,
    scope_type: filters.scopeType === "all" ? undefined : filters.scopeType,
    scope_id: filters.scopeType === "all" ? undefined : (filters.scopeId ?? undefined),
    key_type: filters.keyType === "all" ? undefined : filters.keyType,
    expires_within_days: positiveDays(filters.expiresWithinDays),
    ...(filters.user
      ? {
          [filters.userRelation === "owner" ? "owner_user_id" : "created_by_user_id"]:
            filters.user.id,
          user_relation: filters.userRelation
        }
      : {}),
    search: search && !isFullApiKeySecret(search) ? search : undefined
  };
}

/** How many filters narrow the list (the state tab counts unless it is "all"). */
export function activeFilterCount(filters: AdminKeyFilters, state: ApiKeyStateFilter): number {
  return [
    state !== "all",
    filters.search.trim() !== "",
    filters.user !== null,
    filters.scopeType !== "all",
    filters.scopeType !== "all" && filters.scopeId !== null,
    filters.keyType !== "all",
    positiveDays(filters.expiresWithinDays) !== undefined
  ].filter(Boolean).length;
}
