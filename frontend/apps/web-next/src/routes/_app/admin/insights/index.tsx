import { createFileRoute } from "@tanstack/react-router";
import { validateInsightsPageSearch } from "@/features/admin/insights/insights-page-search";
import { InsightsPage } from "@/features/admin/insights/insights-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/insights/")({
  validateSearch: validateInsightsPageSearch,
  head: routeTitle("insights"),
  component: InsightsPage
});
