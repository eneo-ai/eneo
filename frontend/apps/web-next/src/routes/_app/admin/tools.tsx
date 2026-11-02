import { createFileRoute } from "@tanstack/react-router";
import { bundledToolsQueryOptions, mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { ToolsPage } from "@/features/admin/tools/tools-page";
import { toolsTabOf } from "@/features/admin/tools/tools-tabs";
import { browserApi } from "@/lib/api/browser";
import { readFirstAnswer, readFresh } from "@/lib/api/query";
import { useSearchParams } from "@/lib/navigation";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/tools")({
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      readFresh(queryClient, mcpServersQueryOptions(browserApi)),
      readFresh(queryClient, securityClassificationsQueryOptions(browserApi)),
      // The runtime status sits above the tabs: shown before it answered, it
      // arrived over them and pushed the tabs and the list down (layout shift
      // on a phone). A failed read shows no status card.
      readFirstAnswer(queryClient, bundledToolsQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("tools"),
  component: ToolsRoute
});

function ToolsRoute() {
  const search = useSearchParams();
  return <ToolsPage tab={toolsTabOf(search.get("tab") ?? undefined)} />;
}
