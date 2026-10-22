import type { Metadata } from "next";
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { flowQueryOptions } from "@/features/flows/flows-api";
import { FlowRunPage } from "@/features/flows/runs/run-page";
import { spacePageTitle } from "@/features/spaces/page-title";
import { spaceQueryOptions } from "@/features/spaces/space";

export async function generateMetadata({
  params
}: {
  params: Promise<{ flowId: string }>;
}): Promise<Metadata> {
  const { flowId } = await params;
  return spacePageTitle(
    async () => (await getQueryClient().query(flowQueryOptions(eneoApi(), flowId))).name,
    "flows"
  );
}

/**
 * One run of a flow. The flow and its space are read here (they name the
 * page and its trail); the run itself is read in the browser, where its
 * status is followed while it moves.
 */
export default async function SpaceFlowRunPage({
  params
}: {
  params: Promise<{ spaceId: string; flowId: string; runId: string }>;
}) {
  const { spaceId, flowId, runId } = await params;
  const queryClient = getQueryClient();
  const api = eneoApi();

  try {
    const [space, flow] = await Promise.all([
      queryClient.query(spaceQueryOptions(api, spaceId)),
      queryClient.query(flowQueryOptions(api, flowId))
    ]);
    if (flow.space_id !== space.id) notFound();
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <FlowRunPage flowId={flowId} runId={runId} />
    </HydrationBoundary>
  );
}
