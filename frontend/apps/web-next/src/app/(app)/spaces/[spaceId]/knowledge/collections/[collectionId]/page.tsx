import type { Metadata } from "next";
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  collectionBlobsQueryOptions,
  collectionQueryOptions
} from "@/features/knowledge/knowledge";
import { spacePageTitle } from "@/features/spaces/page-title";
import { CollectionDetail } from "./collection-detail.client";

export async function generateMetadata({
  params
}: {
  params: Promise<{ collectionId: string }>;
}): Promise<Metadata> {
  const { collectionId } = await params;
  return spacePageTitle(
    async () =>
      (await getQueryClient().query(collectionQueryOptions(eneoApi(), collectionId))).name,
    "collections"
  );
}

export default async function CollectionPage({
  params
}: {
  params: Promise<{ spaceId: string; collectionId: string }>;
}) {
  const { collectionId } = await params;
  const queryClient = getQueryClient();
  const api = eneoApi();

  try {
    await Promise.all([
      queryClient.query(collectionQueryOptions(api, collectionId)),
      queryClient.query(collectionBlobsQueryOptions(api, collectionId))
    ]);
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <CollectionDetail collectionId={collectionId} />
    </HydrationBoundary>
  );
}
