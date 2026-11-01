"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { AppWindow, SearchX } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { AREA_HUES } from "@/components/composites/icon-tile";
import { PageHeader } from "@/components/composites/page-header";
import { ResourceCollection } from "@/components/composites/resource-tile";
import { DockedActions } from "@/components/shell/docked-actions";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { filterSpaceResources } from "@/features/spaces/resource-filter";
import { ResourceFilterInput, useFilterShown } from "@/features/spaces/resource-filter-input";
import { useSpace } from "@/features/spaces/use-space";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { AppActionScope } from "./actions";
import { spaceApps, type AppSparse } from "./apps";
import { CreateAppButton } from "./create-app";
import { AppTile } from "./tile";

function TileGrid({ items, showStatus }: { items: AppSparse[]; showStatus: boolean }) {
  return (
    <ResourceCollection>
      {items.map((app) => (
        <AppTile key={app.id} app={app} showStatus={showStatus} />
      ))}
    </ResourceCollection>
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
  const panelRef = useRef<HTMLDivElement>(null);
  // On a phone the title is for screen readers only (the space's active tab names the page), so
  // focus that a removal or an action needs to put somewhere goes to the visible page instead.
  const phone = useMediaMatch(PHONE_QUERY);
  const focusTarget = phone ? panelRef : headingRef;
  const [filter, setFilter] = useState("");

  const items = spaceApps(space, collator.compare);
  const filterShown = useFilterShown(items.length);
  // A filter that is typed and then hidden (fewer items, a turned screen) no longer applies.
  const filteredItems = filterSpaceResources(items, filterShown ? filter : "");
  const showStatus = !space.personal;
  const groupByStatus = can("publish", "app");
  const canCreate = can("create", "app");

  return (
    <RemovalFocusScope target={focusTarget}>
      <AppActionScope focusTarget={focusTarget}>
        <div
          ref={panelRef}
          tabIndex={-1}
          className="focus-visible:outline-ring rounded-ax-element flex w-full flex-col gap-6 focus-visible:outline-2 focus-visible:outline-offset-4"
        >
          <PageHeader
            headingLevel={2}
            headingRef={headingRef}
            title={t("apps")}
            isTitleHiddenOnPhone
            actions={
              canCreate && items.length > 0 ? (
                <DockedActions label={t("space_apps_actions")}>
                  <CreateAppButton />
                </DockedActions>
              ) : undefined
            }
          />
          {items.length === 0 ? (
            <EmptyState
              icon={<AppWindow />}
              hue={AREA_HUES.apps}
              title={t("space_apps_empty_title")}
              description={t("space_apps_empty_description")}
              headingLevel={3}
              actions={canCreate ? <CreateAppButton /> : undefined}
            />
          ) : (
            <>
              {filterShown ? (
                <ResourceFilterInput
                  value={filter}
                  onChange={setFilter}
                  label={t("space_filter_apps_label")}
                  placeholder={t("filter_apps_placeholder")}
                  resultCount={filteredItems.length}
                />
              ) : null}
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
      </AppActionScope>
    </RemovalFocusScope>
  );
}
