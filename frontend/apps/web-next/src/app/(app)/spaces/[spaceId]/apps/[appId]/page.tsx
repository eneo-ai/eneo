import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { appQueryOptions, appRunsQueryOptions } from "@/features/apps/apps";
import { AppDetail } from "@/features/apps/app-detail";

export default async function AppDetailPage({
  params
}: {
  params: Promise<{ spaceId: string; appId: string }>;
}) {
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
      <AppDetail appId={appId} />
    </HydrationBoundary>
  );
}
