import { createFileRoute } from "@tanstack/react-router";
import { AdminIntegrationsPage } from "@/features/admin/integrations/admin-integrations-page";
import { tenantIntegrationsQueryOptions } from "@/features/admin/integrations/integrations";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/integrations")({
  loader: ({ context: { queryClient } }) =>
    readFresh(queryClient, tenantIntegrationsQueryOptions(browserApi)),
  head: routeTitle("integrations"),
  component: AdminIntegrationsPage
});
