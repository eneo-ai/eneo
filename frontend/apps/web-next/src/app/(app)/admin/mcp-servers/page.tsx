import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { McpServersPage } from "@/features/admin/mcp/mcp-page";

export default async function AdminMcpServersRoute() {
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(mcpServersQueryOptions(eneoApi()));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <McpServersPage />
    </HydrationBoundary>
  );
}
