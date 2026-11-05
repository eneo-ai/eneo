import { infiniteQueryOptions, queryOptions, type QueryClient } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { cursorPagination } from "@/lib/api/pagination";

export type UserGroup = Schema<"UserGroupPublic">;
export type GroupMember = Schema<"UserSparse">;

/** Read by the group admin, the user editor and the space and capability-source group pickers. */
export const USER_GROUPS_KEY = ["user-groups"] as const;

/** Users per page in the member picker (the Svelte app's page size). */
export const MEMBER_CANDIDATES_PAGE_SIZE = 100;

/**
 * The organisation's user groups with their members. Any signed-in user may
 * list them (member pickers); every change needs the admin permission, which
 * the backend checks.
 */
export function userGroupsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: USER_GROUPS_KEY,
    queryFn: async (): Promise<UserGroup[]> => (await unwrap(api.GET("/api/v1/user-groups/"))).items
  });
}

/** The organisation's users whose e-mail matches `email` (all without one), a page at a time. */
export function memberCandidatesQueryOptions(api: EneoClient, email: string) {
  return infiniteQueryOptions({
    ...cursorPagination,
    queryKey: ["users", "pages", email],
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET("/api/v1/users/", {
          params: {
            query: {
              email: email || undefined,
              limit: MEMBER_CANDIDATES_PAGE_SIZE,
              cursor: pageParam
            }
          },
          signal
        })
      )
  });
}

/**
 * A group or its members changed: the groups (and the pickers that list them)
 * and the admin user list, whose rows show each user's groups, refetch.
 */
export function refreshUserGroups(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: USER_GROUPS_KEY }),
    queryClient.invalidateQueries({ queryKey: ["admin-users"] })
  ]);
}
