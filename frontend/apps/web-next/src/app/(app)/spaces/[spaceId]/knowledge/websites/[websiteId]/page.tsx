import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  websiteBlobsQueryOptions,
  websiteCrawlRunsQueryOptions,
  websiteQueryOptions
} from "@/features/knowledge/knowledge";
import { WebsiteDetail } from "./website-detail.client";

export default async function WebsitePage({
  params
}: {
  params: Promise<{ spaceId: string; websiteId: string }>;
}) {
  const { websiteId } = await params;
  const queryClient = getQueryClient();
  const api = eneoApi();

  try {
    await Promise.all([
      queryClient.fetchQuery(websiteQueryOptions(api, websiteId)),
      queryClient.fetchQuery(websiteCrawlRunsQueryOptions(api, websiteId)),
      queryClient.fetchQuery(websiteBlobsQueryOptions(api, websiteId))
    ]);
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <WebsiteDetail websiteId={websiteId} />
    </HydrationBoundary>
  );
}
