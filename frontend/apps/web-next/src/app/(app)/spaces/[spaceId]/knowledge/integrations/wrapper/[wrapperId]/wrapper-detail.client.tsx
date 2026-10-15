"use client";

import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { SourcePage } from "@/features/knowledge/integrations/source/source-page";
import { findWrapperSource } from "@/features/knowledge/integrations/sources";
import { useSpace } from "@/features/spaces/use-space";

/**
 * A SharePoint wrapper as one source. The items live on the space object
 * (prefetched by the space layout); once the last one is gone, say so.
 */
export function WrapperDetail({ wrapperId }: { wrapperId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const source = findWrapperSource(
    space.knowledge.integration_knowledge_list.items.filter((item) => item.space_id === space.id),
    wrapperId
  );

  if (!source) {
    return (
      <EmptyState
        title={t("no_results_found")}
        headingLevel={1}
        actions={
          <Button
            label={t("integrations")}
            href={`/spaces/${routeId}/knowledge?tab=integrations`}
          />
        }
      />
    );
  }
  return <SourcePage key={source.id} source={source} />;
}
