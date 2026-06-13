import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { SecurityClassificationsPage } from "@/features/admin/security-classifications/classifications-page";

export default async function AdminSecurityClassificationsRoute() {
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(securityClassificationsQueryOptions(eneoApi()));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <SecurityClassificationsPage />
    </HydrationBoundary>
  );
}
