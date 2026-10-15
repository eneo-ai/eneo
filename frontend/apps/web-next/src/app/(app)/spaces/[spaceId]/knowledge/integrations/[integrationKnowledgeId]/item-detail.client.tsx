"use client";

import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { SourcePage } from "@/features/knowledge/integrations/source/source-page";
import { groupIntegrationSources } from "@/features/knowledge/integrations/sources";
import { useSpace } from "@/features/spaces/use-space";

/** An item imported on its own (a file, a page, a site) as its own source. */
export function ItemDetail({ itemId }: { itemId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const item = space.knowledge.integration_knowledge_list.items.find(
    (entry) => entry.id === itemId && entry.space_id === space.id
  );
  const [source] = item ? groupIntegrationSources([item]) : [];

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
