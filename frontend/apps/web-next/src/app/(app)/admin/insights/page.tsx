import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { insightCountsQueryOptions, InsightsPage } from "@/features/admin/insights/insights-page";

export default async function AdminInsightsRoute() {
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(insightCountsQueryOptions(eneoApi()));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <InsightsPage />
    </HydrationBoundary>
  );
}
