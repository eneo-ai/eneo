"use client";

import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "use-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { useIsRemovingSource } from "@/features/knowledge/integrations/actions";
import { SourcePage } from "@/features/knowledge/integrations/source/source-page";
import { findWrapperSource } from "@/features/knowledge/integrations/sources";
import {
  useSourceItems,
  type LoadedItems
} from "@/features/knowledge/integrations/use-source-items";
import { useSpace } from "@/features/spaces/use-space";

/**
 * A SharePoint wrapper as one source. The items live on the space object
 * (prefetched by the space layout); `loaded` are the items as the server page
 * found them, which stand in while the cached space predates them
 * (useSourceItems). Once the last one is gone, say so.
 */
export function WrapperDetail({ wrapperId, loaded }: { wrapperId: string; loaded: LoadedItems }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const items = useSourceItems(
    routeId,
    findWrapperSource(
      space.knowledge.integration_knowledge_list.items.filter((item) => item.space_id === space.id),
      wrapperId
    )?.items ?? [],
    loaded
  );
  const source = findWrapperSource(items, wrapperId);
  const removing = useIsRemovingSource(space.id, { kind: "wrapper", id: wrapperId });

  if (!source) {
    // Deleted from its own page, which is on its way back to the list.
    if (removing) return null;
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
