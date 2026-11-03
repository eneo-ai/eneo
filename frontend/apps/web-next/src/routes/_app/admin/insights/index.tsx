import { createFileRoute } from "@tanstack/react-router";
import { InsightsPage } from "@/features/admin/insights/insights-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/insights/")({
  head: routeTitle("insights"),
  component: InsightsPage
});
