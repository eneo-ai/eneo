import { dehydrate, HydrationBoundary, noop } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  overviewCrawlerQueryOptions,
  overviewUsageQueryOptions,
  overviewUsersQueryOptions
} from "@/features/admin/overview/overview";
import { AdminOverviewPage } from "@/features/admin/overview/overview-page";

export default async function AdminOverviewRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  // Each card handles its own query error and retry; a failed prefetch must
  // not blank the page. The audit card loads in the browser: its query
  // answers 401 until the admin has opened an access session.
  await Promise.all([
    queryClient.query(overviewUsersQueryOptions(api)).catch(noop),
    queryClient.query(overviewUsageQueryOptions(api)).catch(noop),
    queryClient.query(overviewCrawlerQueryOptions(api)).catch(noop)
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AdminOverviewPage />
    </HydrationBoundary>
  );
}
