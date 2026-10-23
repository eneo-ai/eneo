import { dehydrate, HydrationBoundary, noop } from "@tanstack/react-query";
import { bundledToolsQueryOptions, mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { ToolsPage } from "@/features/admin/tools/tools-page";
import { toolsTabOf } from "@/features/admin/tools/tools-tabs";
import { eneoApi } from "@/lib/api/server";
import { getQueryClient } from "@/lib/api/query";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("tools");

export default async function AdminToolsRoute({
  searchParams
}: {
  searchParams: Promise<{ tab?: string }>;
}) {
  const { tab } = await searchParams;
  const queryClient = getQueryClient();
  const api = eneoApi();
  await Promise.all([
    queryClient.query(mcpServersQueryOptions(api)),
    queryClient.query(securityClassificationsQueryOptions(api)),
    // An older backend without the bundled runtime lists nothing.
    queryClient.query(bundledToolsQueryOptions(api)).catch(noop)
  ]);
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ToolsPage tab={toolsTabOf(tab)} />
    </HydrationBoundary>
  );
}
