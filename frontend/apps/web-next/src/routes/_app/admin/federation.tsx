import { createFileRoute } from "@tanstack/react-router";
import { FederationPage } from "@/features/admin/federation/federation-page";
import { federationQueryOptions } from "@/features/admin/federation/federation";
import { browserApi } from "@/lib/api/browser";
import { warmQuery } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/federation")({
  loader: ({ context: { queryClient } }) => {
    warmQuery(queryClient, federationQueryOptions(browserApi));
  },
  head: routeTitle("federation_admin_title"),
  component: FederationPage
});
