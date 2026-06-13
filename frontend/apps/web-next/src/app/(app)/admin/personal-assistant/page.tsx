import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  GovernancePolicyPage,
  governancePolicyQueryOptions
} from "@/features/admin/governance/governance-policy-page";

export default async function AdminPersonalAssistantRoute() {
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(governancePolicyQueryOptions(eneoApi()));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <GovernancePolicyPage />
    </HydrationBoundary>
  );
}
