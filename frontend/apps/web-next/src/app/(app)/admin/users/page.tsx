import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  adminUsersQueryOptions,
  rolesQueryOptions,
  type StateFilter
} from "@/features/admin/users/users";
import { pageTitle } from "@/lib/page-metadata";
import { AdminUsersPage } from "@/features/admin/users/users-page";

export const generateMetadata = pageTitle("users");

export default async function AdminUsersRoute({
  searchParams
}: {
  searchParams: Promise<{ tab?: string; search?: string; page?: string }>;
}) {
  const { tab, search, page } = await searchParams;
  const queryClient = getQueryClient();
  const api = eneoApi();

  const params = {
    page: Math.max(1, Number(page) || 1),
    stateFilter: (tab === "inactive" ? "inactive" : "active") as StateFilter,
    search: search ?? ""
  };

  await Promise.all([
    queryClient.prefetchQuery(adminUsersQueryOptions(api, params)),
    queryClient.prefetchQuery(rolesQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AdminUsersPage />
    </HydrationBoundary>
  );
}
