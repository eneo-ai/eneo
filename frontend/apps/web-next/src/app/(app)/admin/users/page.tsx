import { dehydrate, HydrationBoundary, noop } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { adminUsersQueryOptions, type StateFilter } from "@/features/admin/users/users";
import { rolesQueryOptions } from "@/features/admin/roles/roles";
import { pageTitle } from "@/lib/page-metadata";
import { AdminUsersPage } from "@/features/admin/users/users-page";

export const generateMetadata = pageTitle("users");

export default async function AdminUsersRoute({
  searchParams
}: {
  searchParams: Promise<{ tab?: string; search?: string; page?: string; role_id?: string }>;
}) {
  const { tab, search, page, role_id } = await searchParams;
  const queryClient = getQueryClient();
  const api = eneoApi();

  const params = {
    page: Math.max(1, Number(page) || 1),
    stateFilter: (tab === "inactive" ? "inactive" : "active") as StateFilter,
    roleId: role_id,
    search: search ?? ""
  };

  await Promise.all([
    queryClient.query(adminUsersQueryOptions(api, params)).catch(noop),
    queryClient.query(rolesQueryOptions(api)).catch(noop)
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AdminUsersPage />
    </HydrationBoundary>
  );
}
