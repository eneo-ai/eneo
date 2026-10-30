import { createFileRoute, notFound } from "@tanstack/react-router";
import { McpServerDetail } from "@/features/admin/mcp/detail/mcp-server-detail";
import { mcpServersQueryOptions, mcpServerToolsQueryOptions } from "@/features/admin/mcp/mcp";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { useSearchParams } from "@/lib/navigation";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/mcp-servers/$id")({
  loader: async ({ context: { queryClient }, params }) => {
    const [servers] = await Promise.all([
      readFresh(queryClient, mcpServersQueryOptions(browserApi)),
      readFresh(queryClient, securityClassificationsQueryOptions(browserApi))
    ]);
    if (!servers.some((server) => server.id === params.id)) throw notFound();
    await readFresh(queryClient, mcpServerToolsQueryOptions(browserApi, params.id));
  },
  remountDeps: ({ params }) => params.id,
  head: routeTitle("mcp_servers"),
  component: McpServerRoute
});

function McpServerRoute() {
  const { id } = Route.useParams();
  const search = useSearchParams();
  return <McpServerDetail serverId={id} initialTab={search.get("tab") ?? undefined} />;
}
