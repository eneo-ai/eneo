import type { Metadata } from "next";
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { flowQueryOptions } from "@/features/flows/flows-api";
import { FlowPage } from "@/features/flows/flow-page";
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

export default async function SpaceFlowPage({
  params
}: {
  params: Promise<{ spaceId: string; flowId: string }>;
}) {
  const { spaceId, flowId } = await params;
  const queryClient = getQueryClient();
  const api = eneoApi();

  try {
    const [space, flow] = await Promise.all([
      queryClient.query(spaceQueryOptions(api, spaceId)),
      queryClient.query(flowQueryOptions(api, flowId))
    ]);
    // A flow is shown under its own space only.
    if (flow.space_id !== space.id) notFound();
  } catch (error) {
    // A flow that is not there, not the caller's to see, or behind the
    // tenant's flows gate is the same 404.
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <FlowPage flowId={flowId} />
    </HydrationBoundary>
  );
}
