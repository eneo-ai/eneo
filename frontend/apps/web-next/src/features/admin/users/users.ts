import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type AdminUser = Schema<"UserAdminView">;
export type PasswordLifecyclePolicy = Schema<"PasswordLifecyclePolicy">;
export type UserState = Schema<"UserState">;
export type StateFilter = "active" | "inactive";

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

/**
 * Every change the user editor makes for one user (its save and its group
 * changes) runs under this mutation key, so the dialog can tell while any of
 * them is in flight (`useIsMutating`) and hold its save and close until done.
 */
export function userEditorMutationKey(userId: string | undefined) {
  return ["admin-user-editor", userId ?? "new"] as const;
}

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
