import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { sourceHref, sourceTabParam } from "@/features/knowledge/integrations/sources";
import { spacePageTitle } from "@/features/spaces/page-title";
import { spaceQueryOptions } from "@/features/spaces/space";
import { ItemDetail } from "./item-detail.client";

type Params = Promise<{ spaceId: string; integrationKnowledgeId: string }>;
type SearchParams = Promise<{ tab?: string | string[] }>;

/**
 * The space's own item; one shared in from another space is not opened here
 * (as on the client). The server copy can stand in until the client rereads
 * its space (useSourceItems). Once per request: the metadata and the page
 * both ask.
 */
const findItem = cache(async (spaceId: string, itemId: string) => {
  try {
    const queryClient = getQueryClient();
    const options = spaceQueryOptions(eneoApi(), spaceId);
    const space = await queryClient.query(options);
    const item = space.knowledge.integration_knowledge_list.items.find(
      (entry) => entry.id === itemId && entry.space_id === space.id
    );
    return item;
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }
});

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { spaceId, integrationKnowledgeId } = await params;
  return spacePageTitle(async () => {
    const item = await findItem(spaceId, integrationKnowledgeId);
    if (!item) throw new Error(`No integration item ${integrationKnowledgeId}`);
    return item.name;
  }, "integrations");
}

/** One imported item; an item that belongs to a wrapper opens as a folder of that source. */
export default async function IntegrationItemPage({
  params,
  searchParams
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { spaceId, integrationKnowledgeId } = await params;
  const { tab } = await searchParams;
  const item = await findItem(spaceId, integrationKnowledgeId);
  if (!item) notFound();
  if (item.wrapper_id && item.integration_type === "sharepoint") {
    redirect(
      sourceHref(
        spaceId,
        { kind: "wrapper", id: item.wrapper_id },
        { folder: item.id, tab: sourceTabParam(tab) }
      )
    );
  }
  return <ItemDetail itemId={integrationKnowledgeId} loaded={{ items: [item] }} />;
}
