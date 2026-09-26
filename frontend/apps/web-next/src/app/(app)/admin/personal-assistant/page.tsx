import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import {
  governancePolicyQueryOptions,
  modelProvidersQueryOptions
} from "@/features/admin/governance/governance";
import { GovernancePolicyPage } from "@/features/admin/governance/governance-policy-page";
import { mcpServersQueryOptions } from "@/features/admin/mcp/mcp";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { promptLibraryQueryOptions } from "@/features/admin/prompt-library/prompt-library";

export const generateMetadata = pageTitle("governance_title");

export default async function AdminPersonalAssistantRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  await Promise.all([
    queryClient.query(governancePolicyQueryOptions(api)),
    queryClient.query(adminModelsQueryOptions(api)),
    queryClient.query(modelProvidersQueryOptions(api)),
    queryClient.query(mcpServersQueryOptions(api)),
    queryClient.query(promptLibraryQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <GovernancePolicyPage />
    </HydrationBoundary>
  );
}
