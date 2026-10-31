import { createFileRoute } from "@tanstack/react-router";
import { InsightsPage } from "@/features/admin/insights/insights-page";
import { insightCountsQueryOptions } from "@/features/admin/insights/insights";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/insights/")({
  loader: ({ context: { queryClient } }) =>
    readFresh(queryClient, insightCountsQueryOptions(browserApi)),
  head: routeTitle("insights"),
  component: InsightsPage
});
