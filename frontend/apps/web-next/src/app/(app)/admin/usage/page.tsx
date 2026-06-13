import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  storageQueryOptions,
  storageSpacesQueryOptions,
  tokenUsageQueryOptions,
  UsagePage
} from "@/features/admin/usage/usage-page";

export default async function AdminUsageRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  await Promise.all([
    queryClient.fetchQuery(tokenUsageQueryOptions(api)),
    queryClient.fetchQuery(storageQueryOptions(api)),
    queryClient.fetchQuery(storageSpacesQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <UsagePage />
    </HydrationBoundary>
  );
}
