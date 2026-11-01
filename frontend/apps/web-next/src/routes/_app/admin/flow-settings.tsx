import { createFileRoute, notFound, redirect } from "@tanstack/react-router";
import { flowSettingsQueryOptions } from "@/features/admin/flow-settings/flow-settings";
import { FlowSettingsPage } from "@/features/admin/flow-settings/flow-settings-page";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";
import { parseSearch } from "@/lib/router/search";

/**
 * The Svelte page had tabs, and its old links say ?tab=: each lands where its
 * settings are now, through the tab's old page where it had one (that page
 * owns the target).
 */
const LEGACY_TABS: Record<string, string> = {
  retention: "/admin/flow-data-retention",
  uploads: "/admin/flow-input-limits",
  evidence: "/admin/flow-knowledge-evidence",
  builder: "/admin/flow-settings#flow-chat"
};

export const Route = createFileRoute("/_app/admin/flow-settings")({
  beforeLoad: ({ location }) => {
    const tab = parseSearch(location.searchStr).tab;
    const target =
      typeof tab === "string" && Object.hasOwn(LEGACY_TABS, tab) ? LEGACY_TABS[tab] : undefined;
    if (target) throw redirect({ href: target, replace: true });
  },
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
