import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type AdminUser = Schema<"UserAdminView">;
export type Role = Schema<"RolePublic">;
export type UserState = Schema<"UserState">;
export type StateFilter = "active" | "inactive";

export const USERS_PAGE_SIZE = 100;
/** Backend rejects 1–2 char searches; only query at 0 or ≥3 chars. */
export const MIN_SEARCH_LENGTH = 3;

export type UsersQueryParams = {
  page: number;
  stateFilter: StateFilter;
  /** Already trimmed; empty string means "no search". */
  search: string;
};

export function adminUsersQueryOptions(api: EneoClient, params: UsersQueryParams) {
  const search = params.search.length >= MIN_SEARCH_LENGTH ? params.search : undefined;
  return queryOptions({
    queryKey: ["admin-users", params],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/admin/users/", {
          params: {
            query: {
              page: params.page,
              page_size: USERS_PAGE_SIZE,
              search_email: search,
              state_filter: params.stateFilter
            }
          }
        })
      )
  });
}

/** Predefined + custom roles, flattened, for the role picker. */
export function rolesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["roles"],
    queryFn: async (): Promise<{ predefined: Role[]; custom: Role[] }> => {
      const response = await unwrap(api.GET("/api/v1/roles/"));
      return {
        predefined: response.predefined_roles.items,
        custom: response.roles.items
      };
    }
  });
}
