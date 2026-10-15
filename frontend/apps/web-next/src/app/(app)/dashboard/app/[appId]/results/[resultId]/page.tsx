import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { appRunQueryOptions } from "@/features/apps/apps";
import { ResultDetail } from "@/features/apps/results/result-detail";

export default async function DashboardAppResultPage({
  params
}: {
  params: Promise<{ appId: string; resultId: string }>;
}) {
  const { appId, resultId } = await params;
  const queryClient = getQueryClient();

  try {
    await queryClient.query(appRunQueryOptions(eneoApi(), resultId));
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  const base = `/dashboard/app/${appId}`;

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      {/* Page padding inside the shell's page panel. */}
      <div className="flex flex-col p-4 sm:p-6">
        <ResultDetail runId={resultId} backHref={base} newRunHref={base} />
      </div>
    </HydrationBoundary>
  );
}
