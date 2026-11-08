import { createFileRoute, notFound } from "@tanstack/react-router";
import { FederationPage } from "@/features/admin/federation/federation-page";
import { federationQueryOptions } from "@/features/admin/federation/federation";
import { browserApi } from "@/lib/api/browser";
import { warmQuery } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/_app/admin/federation")({
  beforeLoad: () => {
    if (!runtimeConfig().federation_enabled) throw notFound();
  },
  loader: ({ context: { queryClient } }) => {
    warmQuery(queryClient, federationQueryOptions(browserApi));
  },
  head: routeTitle("federation_admin_title"),
  component: FederationPage
});
