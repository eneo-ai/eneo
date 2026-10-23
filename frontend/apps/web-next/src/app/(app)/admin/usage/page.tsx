import { dehydrate, HydrationBoundary, noop } from "@tanstack/react-query";
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
  // Each tab handles its own query error and retry; a failed prefetch must not blank the page.
  await Promise.all([
    queryClient.query(tokenUsageQueryOptions(api)).catch(noop),
    queryClient.query(storageQueryOptions(api)).catch(noop),
    queryClient.query(storageSpacesQueryOptions(api)).catch(noop)
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <UsagePage />
    </HydrationBoundary>
  );
}
