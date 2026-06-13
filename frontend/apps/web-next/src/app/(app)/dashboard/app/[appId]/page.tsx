import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { appQueryOptions, appRunsQueryOptions } from "@/features/apps/apps";
import { DashboardApp } from "./dashboard-app.client";

export default async function DashboardAppPage({ params }: { params: Promise<{ appId: string }> }) {
  const { appId } = await params;
  const queryClient = getQueryClient();
  const api = eneoApi();

  try {
    await Promise.all([
      queryClient.fetchQuery(appQueryOptions(api, appId)),
      queryClient.fetchQuery(appRunsQueryOptions(api, appId))
    ]);
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <DashboardApp appId={appId} />
    </HydrationBoundary>
  );
}
