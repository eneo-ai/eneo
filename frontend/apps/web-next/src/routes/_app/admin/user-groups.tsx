import { createFileRoute } from "@tanstack/react-router";
import { AdminUserGroupsPage } from "@/features/admin/user-groups/user-groups-page";
import { userGroupsQueryOptions } from "@/features/admin/user-groups/user-groups";
import { browserApi } from "@/lib/api/browser";
import { warmQuery } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/user-groups")({
  loader: ({ context: { queryClient } }) => {
    warmQuery(queryClient, userGroupsQueryOptions(browserApi));
  },
  head: routeTitle("user_groups"),
  component: AdminUserGroupsPage
});
