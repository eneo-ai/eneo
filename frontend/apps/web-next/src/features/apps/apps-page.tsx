"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { AppWindow, SearchX } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { RESOURCE_GRID_CLASS } from "@/components/composites/resource-tile";
import { SpaceSectionHeader } from "@/features/spaces/frame/space-section-header";
import { filterSpaceResources } from "@/features/spaces/resource-filter";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { useSpace } from "@/features/spaces/use-space";
import { spaceApps, type AppSparse } from "./apps";
import { CreateAppButton } from "./create-app";
import { AppTile } from "./tile";

function TileGrid({ items, showStatus }: { items: AppSparse[]; showStatus: boolean }) {
  return (
    <ul className={RESOURCE_GRID_CLASS}>
      {items.map((app) => (
        <li key={app.id} className="min-w-0">
          <AppTile app={app} showStatus={showStatus} />
        </li>
      ))}
    </ul>
  );
}

/** Apps in one grid, grouped into published/drafts for users who can publish. */
export function AppsPage() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const collator = useCollator();
  const [filter, setFilter] = useState("");

  const items = spaceApps(space, collator.compare);
  const filteredItems = filterSpaceResources(items, filter);
  const showStatus = !space.personal;
  const groupByStatus = can("publish", "app");
  const canCreate = can("create", "app");
  const published = filteredItems.filter((app) => app.published);
  const drafts = filteredItems.filter((app) => !app.published);

  return (
    <div className="flex w-full flex-col gap-6">
      <SpaceSectionHeader
        title={t("apps")}
        actions={canCreate && items.length > 0 ? <CreateAppButton /> : undefined}
      />
      {items.length === 0 ? (
        <EmptyState
          icon={<AppWindow />}
          title={t("space_apps_empty_title")}
          description={t("space_apps_empty_description")}
          actions={canCreate ? <CreateAppButton /> : undefined}
        />
      ) : (
        <>
          <ResourceFilterInput
            value={filter}
            onChange={setFilter}
            placeholder={t("filter_apps_placeholder")}
          />
          {filteredItems.length === 0 ? (
            <EmptyState icon={<SearchX />} title={t("no_results_found")} isCompact />
          ) : groupByStatus ? (
            <div className="flex flex-col gap-6">
              {published.length > 0 && (
                <section aria-labelledby="apps-published" className="flex flex-col gap-3">
                  <h3 id="apps-published" className="text-ax-text-secondary text-sm font-semibold">
                    {t("published")}
                  </h3>
                  <TileGrid items={published} showStatus={false} />
                </section>
              )}
              {drafts.length > 0 && (
                <section aria-labelledby="apps-drafts" className="flex flex-col gap-3">
                  <h3 id="apps-drafts" className="text-ax-text-secondary text-sm font-semibold">
                    {t("drafts")}
                  </h3>
                  <TileGrid items={drafts} showStatus={false} />
                </section>
              )}
            </div>
          ) : (
            <TileGrid items={filteredItems} showStatus={showStatus} />
          )}
        </>
      )}
    </div>
  );
}
