import type { Metadata } from "next";
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { env } from "@/lib/env";
import {
  formatWebsiteName,
  websiteBlobsQueryOptions,
  websiteCrawlRunsQueryOptions,
  websiteQueryOptions
} from "@/features/knowledge/knowledge";
import { spacePageTitle } from "@/features/spaces/page-title";
import { WebsiteDetail } from "./website-detail.client";

export async function generateMetadata({
  params
}: {
  params: Promise<{ websiteId: string }>;
}): Promise<Metadata> {
  const { websiteId } = await params;
  return spacePageTitle(
    async () =>
      formatWebsiteName(await getQueryClient().query(websiteQueryOptions(eneoApi(), websiteId))),
    "websites"
  );
}

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
      queryClient.query(websiteQueryOptions(api, websiteId)),
      queryClient.query(websiteCrawlRunsQueryOptions(api, websiteId)),
      queryClient.query(websiteBlobsQueryOptions(api, websiteId))
    ]);
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <WebsiteDetail
        websiteId={websiteId}
        integrationRequestFormUrl={env.REQUEST_INTEGRATION_FORM_URL}
      />
    </HydrationBoundary>
  );
}
