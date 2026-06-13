import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  appTemplatesQueryOptions,
  assistantTemplatesQueryOptions,
  TemplatesPage
} from "@/features/admin/templates/templates-page";

export default async function AdminTemplatesRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  await Promise.all([
    queryClient.fetchQuery(assistantTemplatesQueryOptions(api)),
    queryClient.fetchQuery(appTemplatesQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <TemplatesPage />
    </HydrationBoundary>
  );
}
