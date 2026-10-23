import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { findWrapperSource } from "@/features/knowledge/integrations/sources";
import { spacePageTitle } from "@/features/spaces/page-title";
import { spaceQueryOptions } from "@/features/spaces/space";
import { WrapperDetail } from "./wrapper-detail.client";

type Params = Promise<{ spaceId: string; wrapperId: string }>;

/**
 * The space's own items imported under the wrapper, as one source (as on the
 * client). The server copy can stand in until the client rereads its space
 * (useSourceItems). Once per request: the metadata and the page both ask.
 */
const findWrapper = cache(async (spaceId: string, wrapperId: string) => {
  try {
    const queryClient = getQueryClient();
    const options = spaceQueryOptions(eneoApi(), spaceId);
    const space = await queryClient.query(options);
    const source = findWrapperSource(
      space.knowledge.integration_knowledge_list.items.filter((item) => item.space_id === space.id),
      wrapperId
    );
    return source;
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }
});

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { spaceId, wrapperId } = await params;
  return spacePageTitle(async () => {
    const source = await findWrapper(spaceId, wrapperId);
    if (!source) throw new Error(`No integration items in wrapper ${wrapperId}`);
    return source.name;
  }, "integrations");
}

/** A SharePoint wrapper as one source; an unknown wrapper (or one whose last item is gone) is a 404. */
export default async function WrapperPage({ params }: { params: Params }) {
  const { spaceId, wrapperId } = await params;
  const source = await findWrapper(spaceId, wrapperId);
  if (!source) notFound();
  return <WrapperDetail wrapperId={wrapperId} loaded={{ items: source.items }} />;
}
