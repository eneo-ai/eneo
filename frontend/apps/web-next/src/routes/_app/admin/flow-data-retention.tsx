import { createFileRoute } from "@tanstack/react-router";
import { FlowRetentionPage } from "@/features/admin/flow-retention/flow-retention-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/flow-data-retention")({
  head: routeTitle("flow_retention_admin_title"),
  component: FlowRetentionPage
});
