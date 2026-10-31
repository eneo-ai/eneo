import { createFileRoute } from "@tanstack/react-router";
import { ModelsPage } from "@/features/admin/models/models-page";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import {
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions
} from "@/features/admin/models/model-providers";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { readFresh, warmQuery } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/models")({
  loader: async ({ context: { queryClient } }) => {
    warmQuery(queryClient, modelProvidersQueryOptions(browserApi));
    warmQuery(queryClient, providerCapabilitiesQueryOptions(browserApi));
    await Promise.all([
      readFresh(queryClient, adminModelsQueryOptions(browserApi)),
      readFresh(queryClient, securityClassificationsQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("models"),
  component: ModelsPage
});
