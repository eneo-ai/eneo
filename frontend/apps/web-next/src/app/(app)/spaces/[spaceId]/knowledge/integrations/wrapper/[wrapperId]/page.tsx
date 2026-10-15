import type { Metadata } from "next";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { groupIntegrationSources } from "@/features/knowledge/integrations/sources";
import { spacePageTitle } from "@/features/spaces/page-title";
import { spaceQueryOptions } from "@/features/spaces/space";
import { WrapperDetail } from "./wrapper-detail.client";

export async function generateMetadata({
  params
}: {
  params: Promise<{ spaceId: string; wrapperId: string }>;
}): Promise<Metadata> {
  const { spaceId, wrapperId } = await params;
  return spacePageTitle(async () => {
    const space = await getQueryClient().query(spaceQueryOptions(eneoApi(), spaceId));
    const source = groupIntegrationSources(space.knowledge.integration_knowledge_list.items).find(
      (entry) => entry.kind === "wrapper" && entry.id === wrapperId
    );
    if (!source) throw new Error(`No integration items in wrapper ${wrapperId}`);
    return source.name;
  }, "integrations");
}

export default async function WrapperPage({
  params
}: {
  params: Promise<{ spaceId: string; wrapperId: string }>;
}) {
  const { wrapperId } = await params;
  return <WrapperDetail wrapperId={wrapperId} />;
}
