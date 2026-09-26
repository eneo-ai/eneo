import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  storageQueryOptions,
  storageSpacesQueryOptions,
  tokenUsageQueryOptions
} from "@/features/admin/usage/usage";
import { UsagePage } from "@/features/admin/usage/usage-page";

export default async function AdminUsageRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  await Promise.all([
    queryClient.query(tokenUsageQueryOptions(api)),
    queryClient.query(storageQueryOptions(api)),
    queryClient.query(storageSpacesQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <UsagePage />
    </HydrationBoundary>
  );
}
