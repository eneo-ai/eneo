import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { mcpServersQueryOptions, mcpServerToolsQueryOptions } from "@/features/admin/mcp/mcp";
import { McpServerDetail } from "@/features/admin/mcp/detail/mcp-server-detail";

export const generateMetadata = pageTitle("mcp_servers");

export default async function AdminMcpServerDetailRoute({
  params,
  searchParams
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { id } = await params;
  const { tab } = await searchParams;
  const queryClient = getQueryClient();
  const api = eneoApi();

  const [servers] = await Promise.all([
    queryClient.fetchQuery(mcpServersQueryOptions(api)),
    queryClient.fetchQuery(securityClassificationsQueryOptions(api)),
    queryClient.fetchQuery(mcpServerToolsQueryOptions(api, id))
  ]);

  if (!servers.some((server) => server.id === id)) notFound();

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <McpServerDetail serverId={id} initialTab={tab} />
    </HydrationBoundary>
  );
}
