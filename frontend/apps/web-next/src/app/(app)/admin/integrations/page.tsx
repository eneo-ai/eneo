import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  AdminIntegrationsPage,
  tenantIntegrationsQueryOptions
} from "@/features/admin/integrations/admin-integrations-page";

export default async function AdminIntegrationsRoute() {
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(tenantIntegrationsQueryOptions(eneoApi()));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AdminIntegrationsPage />
    </HydrationBoundary>
  );
}
