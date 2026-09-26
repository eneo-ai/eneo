"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { AppWindow, SearchX } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { RESOURCE_GRID_CLASS } from "@/components/composites/resource-tile";
import { RemovalFocusScope } from "@/features/spaces/removal";
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

/** A titled group of cards (Publicerad / Utkast). */
function TileGroup({ title, items }: { title: string; items: AppSparse[] }) {
  const headingId = useId();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h3 id={headingId} className="text-ax-text-secondary text-sm font-semibold">
        {title}
      </h3>
      <TileGrid items={items} showStatus={false} />
    </section>
  );
}

/** Apps in one grid, grouped into published/drafts for users who can publish. */
export function AppsPage() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const collator = useCollator();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [filter, setFilter] = useState("");

  const items = spaceApps(space, collator.compare);
  const filteredItems = filterSpaceResources(items, filter);
  const showStatus = !space.personal;
  const groupByStatus = can("publish", "app");
  const canCreate = can("create", "app");

  return (
    <RemovalFocusScope target={headingRef}>
      <div className="flex w-full flex-col gap-6">
        <PageHeader
          headingLevel={2}
          headingRef={headingRef}
          title={t("apps")}
          actions={canCreate && items.length > 0 ? <CreateAppButton /> : undefined}
        />
        {items.length === 0 ? (
          <EmptyState
            icon={<AppWindow />}
            title={t("space_apps_empty_title")}
            description={t("space_apps_empty_description")}
            headingLevel={3}
            actions={canCreate ? <CreateAppButton /> : undefined}
          />
        ) : (
          <>
            <ResourceFilterInput
              value={filter}
              onChange={setFilter}
              label={t("space_filter_apps_label")}
              placeholder={t("filter_apps_placeholder")}
              resultCount={filteredItems.length}
            />
            {filteredItems.length === 0 ? (
              <EmptyState
                icon={<SearchX />}
                title={t("no_results_found")}
                headingLevel={3}
                isCompact
              />
            ) : groupByStatus ? (
              <div className="flex flex-col gap-6">
                <TileGroup
                  title={t("published")}
                  items={filteredItems.filter((app) => app.published)}
                />
                <TileGroup
                  title={t("drafts")}
                  items={filteredItems.filter((app) => !app.published)}
                />
              </div>
            ) : (
              <TileGrid items={filteredItems} showStatus={showStatus} />
            )}
          </>
        )}
      </div>
    </RemovalFocusScope>
  );
}
