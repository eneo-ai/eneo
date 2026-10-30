import { createFileRoute, notFound } from "@tanstack/react-router";
import { flowSettingsQueryOptions } from "@/features/admin/flow-settings/flow-settings";
import { FlowSettingsPage } from "@/features/admin/flow-settings/flow-settings-page";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/flow-settings")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context: { queryClient } }) => {
      try {
        await readFresh(queryClient, flowSettingsQueryOptions(browserApi));
      } catch (error) {
        if (error instanceof EneoApiError && error.status === 404) throw notFound();
        // Other failures stay with the page's shared QueryStateBoundary and retry.
      }
    }
  },
  head: routeTitle("flow_admin_title"),
  component: FlowSettingsPage
});
