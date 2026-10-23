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
      queryClient.query(appQueryOptions(api, appId)),
      queryClient.query(appRunsQueryOptions(api, appId))
    ]);
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      {/* Page padding inside the shell's page panel. */}
      <div className="flex flex-col p-4 sm:p-6">
        <DashboardApp appId={appId} />
      </div>
    </HydrationBoundary>
  );
}
