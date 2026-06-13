import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { appQueryOptions, appRunQueryOptions } from "@/features/apps/apps";
import { ResultDetail } from "@/features/apps/results/result-detail";

export default async function AppResultPage({
  params
}: {
  params: Promise<{ spaceId: string; appId: string; resultId: string }>;
}) {
  const { spaceId, appId, resultId } = await params;
  const queryClient = getQueryClient();
  const api = eneoApi();

  let canEdit = false;
  try {
    const [app] = await Promise.all([
      queryClient.fetchQuery(appQueryOptions(api, appId)),
      queryClient.fetchQuery(appRunQueryOptions(api, resultId))
    ]);
    canEdit = (app.permissions ?? []).includes("edit");
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  const base = `/spaces/${spaceId}/apps/${appId}`;

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ResultDetail
        runId={resultId}
        backHref={base}
        editHref={canEdit ? `${base}/edit` : undefined}
        newRunHref={base}
      />
    </HydrationBoundary>
  );
}
