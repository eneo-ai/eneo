import { createFileRoute } from "@tanstack/react-router";
import { bundledToolsQueryOptions, mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { ToolsPage } from "@/features/admin/tools/tools-page";
import { toolsTabOf } from "@/features/admin/tools/tools-tabs";
import { browserApi } from "@/lib/api/browser";
import { readFresh, warmQuery } from "@/lib/api/query";
import { useSearchParams } from "@/lib/navigation";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/tools")({
  loader: async ({ context: { queryClient } }) => {
    warmQuery(queryClient, bundledToolsQueryOptions(browserApi));
    await Promise.all([
      readFresh(queryClient, mcpServersQueryOptions(browserApi)),
      readFresh(queryClient, securityClassificationsQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("tools"),
  component: ToolsRoute
});

function ToolsRoute() {
  const search = useSearchParams();
  return <ToolsPage tab={toolsTabOf(search.get("tab") ?? undefined)} />;
}
