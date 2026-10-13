import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { CapabilityProvidersPage } from "@/features/admin/tools/capability-providers-page";
import { eneoApi } from "@/lib/api/server";
import { getQueryClient } from "@/lib/api/query";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("tools");

export default async function AdminToolsRoute() {
  const queryClient = getQueryClient();
  await queryClient.query(mcpServersQueryOptions(eneoApi()));
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <CapabilityProvidersPage />
    </HydrationBoundary>
  );
}
