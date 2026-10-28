import { dehydrate, HydrationBoundary, noop } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  overviewCrawlerQueryOptions,
  overviewUsageQueryOptions,
  overviewUsersQueryOptions
} from "@/features/admin/overview/overview";
import { AdminOverviewPage } from "@/features/admin/overview/overview-page";
import {
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions
} from "@/features/admin/models/model-providers";
import { adminModelsQueryOptions } from "@/features/admin/models/models";

export default async function AdminOverviewRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  // Each card handles its own query error and retry; a failed prefetch must
  // not blank the page. The audit card loads in the browser: its query
  // answers 401 until the admin has opened an access session. The models
  // queries feed "Behöver åtgärd", so it is there on arrival rather than
  // pushing the page down as it loads; only a key's expiry waits for the
  // viewer's date, after hydration (as on the models page).
  await Promise.all([
    queryClient.query(overviewUsersQueryOptions(api)).catch(noop),
    queryClient.query(overviewUsageQueryOptions(api)).catch(noop),
    queryClient.query(overviewCrawlerQueryOptions(api)).catch(noop),
    queryClient.query(adminModelsQueryOptions(api)).catch(noop),
    queryClient.query(modelProvidersQueryOptions(api)).catch(noop),
    queryClient.query(providerCapabilitiesQueryOptions(api)).catch(noop)
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AdminOverviewPage />
    </HydrationBoundary>
  );
}
