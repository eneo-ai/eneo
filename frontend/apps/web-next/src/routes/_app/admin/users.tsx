import { createFileRoute } from "@tanstack/react-router";
import { AdminUsersPage } from "@/features/admin/users/users-page";
import {
  adminPasswordPolicyQueryOptions,
  adminUsersQueryOptions,
  readUsersFilters
} from "@/features/admin/users/users";
import { rolesQueryOptions } from "@/features/admin/roles/roles";
import { browserApi } from "@/lib/api/browser";
import { warmQuery } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/users")({
  loader: ({ context: { queryClient }, location }) => {
    const filters = readUsersFilters(new URLSearchParams(location.searchStr));
    warmQuery(
      queryClient,
      adminUsersQueryOptions(browserApi, {
        ...filters,
        roleId: filters.roleId ?? undefined,
        searchName: filters.searchName || undefined
      })
    );
    warmQuery(queryClient, rolesQueryOptions(browserApi));
    warmQuery(queryClient, adminPasswordPolicyQueryOptions(browserApi));
  },
  head: routeTitle("users"),
  component: AdminUsersPage
});
