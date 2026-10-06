import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  appTemplatesQueryOptions,
  assistantTemplatesQueryOptions
} from "@/features/admin/templates/templates";
import { pageTitle } from "@/lib/page-metadata";
import { TemplatesPage } from "@/features/admin/templates/templates-page";

export const generateMetadata = pageTitle("templates");

export default async function AdminTemplatesRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  await Promise.all([
    queryClient.query(assistantTemplatesQueryOptions(api)),
    queryClient.query(appTemplatesQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <TemplatesPage />
    </HydrationBoundary>
  );
}
