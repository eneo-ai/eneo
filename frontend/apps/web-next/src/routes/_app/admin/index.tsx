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
import { readFirstAnswer, warmQuery } from "@/lib/api/query";

export const Route = createFileRoute("/_app/admin/")({
  loader: async ({ context: { queryClient } }) => {
    warmQuery(queryClient, overviewUsersQueryOptions(browserApi));
    warmQuery(queryClient, overviewUsageQueryOptions(browserApi));
    // "Behöver åtgärd" leads the page and is built from these: shown before
    // they answered, it arrived above the areas and pushed them down (layout
    // shift on a phone). A failed read adds nothing; the area's own row says why.
    await Promise.all([
      readFirstAnswer(queryClient, overviewCrawlerQueryOptions(browserApi)),
      readFirstAnswer(queryClient, adminModelsQueryOptions(browserApi)),
      readFirstAnswer(queryClient, modelProvidersQueryOptions(browserApi)),
      readFirstAnswer(queryClient, providerCapabilitiesQueryOptions(browserApi))
    ]);
  },
  component: AdminOverviewPage
});
