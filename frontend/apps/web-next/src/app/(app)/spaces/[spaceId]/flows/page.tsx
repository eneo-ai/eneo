import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound, redirect } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import { flowsListQueryOptions } from "@/features/flows/flows-api";
import { FlowsPage } from "@/features/flows/flows-page";
import { spaceQueryOptions } from "@/features/spaces/space";

// The space layout's title template adds the space: "Flöden · Upphandling · Eneo".
export const generateMetadata = pageTitle("flows");

export default async function SpaceFlowsPage({ params }: { params: Promise<{ spaceId: string }> }) {
  const { spaceId } = await params;
  // Flows belong to a space's work; the organization space has none.
  if (spaceId === "organization") redirect("/spaces/organization/knowledge");

  const queryClient = getQueryClient();
  const api = eneoApi();
  const space = await queryClient.query(spaceQueryOptions(api, spaceId));
  try {
    await queryClient.query(flowsListQueryOptions(api, space.id));
  } catch (error) {
    // The tenant's flows gate answers 404 when flows are off.
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <FlowsPage />
    </HydrationBoundary>
  );
}
