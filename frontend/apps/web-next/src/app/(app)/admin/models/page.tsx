import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { ModelsPage } from "@/features/admin/models/models-page";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";

export default async function AdminModelsRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();

  await Promise.all([
    queryClient.fetchQuery(adminModelsQueryOptions(api)),
    queryClient.fetchQuery(securityClassificationsQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ModelsPage />
    </HydrationBoundary>
  );
}
