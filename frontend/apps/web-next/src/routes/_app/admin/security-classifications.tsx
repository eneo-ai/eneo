import { createFileRoute } from "@tanstack/react-router";
import { SecurityClassificationsPage } from "@/features/admin/security-classifications/classifications-page";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/security-classifications")({
  loader: ({ context: { queryClient } }) =>
    readFresh(queryClient, securityClassificationsQueryOptions(browserApi)),
  head: routeTitle("security_classifications"),
  component: SecurityClassificationsPage
});
