import { createFileRoute } from "@tanstack/react-router";
import { AdminOverviewPage } from "@/features/admin/overview/overview-page";
import {
  overviewCrawlerQueryOptions,
  overviewUsageQueryOptions,
  overviewUsersQueryOptions
} from "@/features/admin/overview/overview";
import {
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions
} from "@/features/admin/models/model-providers";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { browserApi } from "@/lib/api/browser";
import { warmQuery } from "@/lib/api/query";

export const Route = createFileRoute("/_app/admin/")({
  loader: ({ context: { queryClient } }) => {
    warmQuery(queryClient, overviewUsersQueryOptions(browserApi));
    warmQuery(queryClient, overviewUsageQueryOptions(browserApi));
    warmQuery(queryClient, overviewCrawlerQueryOptions(browserApi));
    warmQuery(queryClient, adminModelsQueryOptions(browserApi));
    warmQuery(queryClient, modelProvidersQueryOptions(browserApi));
    warmQuery(queryClient, providerCapabilitiesQueryOptions(browserApi));
  },
  component: AdminOverviewPage
});
