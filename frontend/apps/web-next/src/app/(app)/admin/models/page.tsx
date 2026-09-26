import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import {
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions
} from "@/features/admin/models/model-providers";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { ModelsPage } from "@/features/admin/models/models-page";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";

export const generateMetadata = pageTitle("models");

export default async function AdminModelsRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();

  await Promise.all([
    queryClient.fetchQuery(adminModelsQueryOptions(api)),
    queryClient.fetchQuery(securityClassificationsQueryOptions(api)),
    // Custom providers and their field definitions drive the provider cards
    // + key status. Prefetch (swallows errors) so cards paint on first render
    // without failing SSR.
    queryClient.prefetchQuery(modelProvidersQueryOptions(api)),
    queryClient.prefetchQuery(providerCapabilitiesQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ModelsPage />
    </HydrationBoundary>
  );
}
