"use client";

import { Button } from "@astryxdesign/core/Button";
import { useCollator } from "@astryxdesign/core/i18n";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { useIsRemovingSource } from "@/features/knowledge/integrations/actions";
import { SourcePage } from "@/features/knowledge/integrations/source/source-page";
import { groupIntegrationSources } from "@/features/knowledge/integrations/sources";
import {
  useSourceItems,
  type LoadedItems
} from "@/features/knowledge/integrations/use-source-items";
import { useSpace } from "@/features/spaces/use-space";

/**
 * An item imported on its own (a file, a page, a site) as its own source.
 * `loaded` is the item as the server page found it, which stands in while the
 * cached space predates it (useSourceItems).
 */
export function ItemDetail({ itemId, loaded }: { itemId: string; loaded: LoadedItems }) {
  const t = useTranslations();
  const collator = useCollator();
  const { space, routeId } = useSpace();
  const items = useSourceItems(
    routeId,
    space.knowledge.integration_knowledge_list.items.filter(
      (entry) => entry.id === itemId && entry.space_id === space.id
    ),
    loaded
  );
  const [source] = groupIntegrationSources(items, collator.compare);
  const removing = useIsRemovingSource(space.id, { kind: "item", id: itemId });

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
