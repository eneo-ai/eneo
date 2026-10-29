import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type AdminUser = Schema<"UserAdminView">;
export type PasswordLifecyclePolicy = Schema<"PasswordLifecyclePolicy">;
export type UserState = Schema<"UserState">;
export type StateFilter = "active" | "inactive";

export type UsersFilters = {
  stateFilter: StateFilter;
  search: string;
  searchName: string;
  page: number;
  roleId: string | null;
};

export function readUsersFilters(params: Pick<URLSearchParams, "get">): UsersFilters {
  const page = Number(params.get("page"));
  return {
    stateFilter: params.get("tab") === "inactive" ? "inactive" : "active",
    search: params.get("search")?.trim() ?? "",
    searchName: params.get("search_name")?.trim() ?? "",
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    roleId: params.get("role_id")?.trim() || null
  };
}

export function usersFiltersSearchParams(filters: UsersFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.stateFilter !== "active") params.set("tab", filters.stateFilter);
  if (filters.search) params.set("search", filters.search);
  if (filters.searchName) params.set("search_name", filters.searchName);
  if (filters.page > 1) params.set("page", String(filters.page));
  if (filters.roleId) params.set("role_id", filters.roleId);
  return params;
}

export const USERS_PAGE_SIZE = 100;
/** Backend rejects 1–2 char searches; only query at 0 or ≥3 chars. */
export const MIN_SEARCH_LENGTH = 3;

/** A search the backend accepts: none, or at least `MIN_SEARCH_LENGTH` characters. */
export function isSearchable(value: string): boolean {
  return value.length === 0 || value.length >= MIN_SEARCH_LENGTH;
}

export type UsersQueryParams = {
  page: number;
  stateFilter: StateFilter;
  roleId?: string;
  /** E-mail search, already trimmed; empty string means "no search". */
  search: string;
  /**
   * Username search, likewise, combined with the e-mail search (AND). Left
   * out for none, so the key matches the callers that never search by name.
   */
  searchName?: string;
};

export const ADMIN_PASSWORD_POLICY_KEY = ["admin-password-policy"] as const;

/** When local passwords in this organisation must be replaced (admin only). */
export function adminPasswordPolicyQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ADMIN_PASSWORD_POLICY_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/admin/password-policy"))
  });
}

export function adminUsersQueryOptions(api: EneoClient, params: UsersQueryParams) {
  const searched = (value: string) => (value.length >= MIN_SEARCH_LENGTH ? value : undefined);
  return queryOptions({
    queryKey: ["admin-users", params],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/admin/users/", {
          params: {
            query: {
              page: params.page,
              page_size: USERS_PAGE_SIZE,
              search_email: searched(params.search),
              search_name: searched(params.searchName ?? ""),
              state_filter: params.stateFilter,
              role_id: params.roleId
            }
          }
        })
      )
  });
}
