import { createFileRoute } from "@tanstack/react-router";
import { GovernancePolicyPage } from "@/features/admin/governance/governance-policy-page";
import {
  governancePolicyQueryOptions,
  skillRuntimePolicyQueryOptions
} from "@/features/admin/governance/governance";
import { mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { modelProvidersQueryOptions } from "@/features/admin/models/model-providers";
import { promptLibraryQueryOptions } from "@/features/admin/prompt-library/prompt-library";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/personal-assistant")({
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      readFresh(queryClient, governancePolicyQueryOptions(browserApi)),
      readFresh(queryClient, adminModelsQueryOptions(browserApi)),
      readFresh(queryClient, modelProvidersQueryOptions(browserApi)),
      readFresh(queryClient, mcpServersQueryOptions(browserApi)),
      readFresh(queryClient, promptLibraryQueryOptions(browserApi)),
      readFresh(queryClient, skillRuntimePolicyQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("governance_title"),
  component: GovernancePolicyPage
});
