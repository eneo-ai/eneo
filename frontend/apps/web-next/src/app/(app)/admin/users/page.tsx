import { dehydrate, HydrationBoundary, noop } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  adminPasswordPolicyQueryOptions,
  adminUsersQueryOptions,
  readUsersFilters
} from "@/features/admin/users/users";
import { rolesQueryOptions } from "@/features/admin/roles/roles";
import { pageTitle } from "@/lib/page-metadata";
import { AdminUsersPage } from "@/features/admin/users/users-page";

export const generateMetadata = pageTitle("users");

export default async function AdminUsersRoute({
  searchParams
}: {
  searchParams: Promise<{
    tab?: string;
    search?: string;
    search_name?: string;
    page?: string;
    role_id?: string;
  }>;
}) {
  const raw = await searchParams;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(raw)) {
    if (value !== undefined) search.set(key, value);
  }
  const filters = readUsersFilters(search);
  const queryClient = getQueryClient();
  const api = eneoApi();

  const params = {
    ...filters,
    roleId: filters.roleId ?? undefined,
    searchName: filters.searchName || undefined
  };

  await Promise.all([
    queryClient.query(adminUsersQueryOptions(api, params)).catch(noop),
    queryClient.query(rolesQueryOptions(api)).catch(noop),
    queryClient.query(adminPasswordPolicyQueryOptions(api)).catch(noop)
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AdminUsersPage />
    </HydrationBoundary>
  );
}
