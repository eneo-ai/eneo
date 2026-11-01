"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { AppWindow, SearchX } from "lucide-react";
import { useTranslations } from "use-intl";
import { useCallback, useMemo, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { AREA_HUES } from "@/components/composites/icon-tile";
import { PageHeader } from "@/components/composites/page-header";
import { Table } from "@/components/astryx/table";
import {
  pixel,
  proportional,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type TableSortComparator
} from "@astryxdesign/core/Table";
import { ResourceGroup } from "@/components/composites/resource-group";
import { StatusLabel } from "@/components/composites/status-label";
import Link from "@/lib/link";
import { ResourceViewControls, useResourceView } from "@/features/spaces/resource-view";
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
import { AppActions } from "./actions";
import { AppTile } from "./tile";

export function AppsPage() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const collator = useCollator();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  // On a phone the title is for screen readers only (the space's active tab names the page), so
  // focus that a removal or an action needs to put somewhere goes to the visible page instead.
  const phone = useMediaMatch(PHONE_QUERY);
  const focusTarget = phone ? panelRef : headingRef;
  const [filter, setFilter] = useState("");

  const items = useMemo(() => spaceApps(space, collator.compare), [space, collator]);
  const filterShown = useFilterShown(items.length);
  const matchedItems = useMemo(
    () => filterSpaceResources(items, filterShown ? filter : ""),
    [items, filter, filterShown]
  );
  const { view, chooseView } = useResourceView("apps", "cards");
  const comparePublished = useCallback(
    (a: boolean, b: boolean) =>
      collator.compare(t(a ? "published" : "draft"), t(b ? "published" : "draft")),
    [collator, t]
  );
  const comparators = useMemo<Record<"name" | "published", TableSortComparator<AppSparse>>>(
    () => ({
      name: (a, b) => collator.compare(a.name, b.name),
      published: (a, b) => comparePublished(a.published, b.published)
    }),
    [collator, comparePublished]
  );
  const { sortedData: filteredItems, sortConfig } = useTableSortableState<
    AppSparse,
    "name" | "published"
  >({
    data: matchedItems,
    comparators,
    defaultSort: [{ sortKey: "name", direction: "ascending" }],
    allowUnsortedState: false
  });
  const sortPlugin = useTableSortable<AppSparse, "name" | "published">(sortConfig);
  const showStatus = !space.personal;
  const groupByStatus = can("publish", "app");
  const canCreate = can("create", "app");

  const columns: TableColumn<AppSparse>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(2),
      sortable: true,
      renderCell: (item) => (
        <Link href={`/spaces/${routeId}/apps/${item.id}`} className="font-medium hover:underline">
          {item.name}
        </Link>
      )
    },
    ...(showStatus
      ? [
          {
            key: "published",
            header: t("status"),
            width: proportional(1),
            sortable: true,
            renderCell: (item: AppSparse) => (
              <StatusLabel
                status={item.published ? "success" : "neutral"}
                label={t(item.published ? "published" : "draft")}
              />
            )
          }
        ]
      : []),
    {
      key: "actions",
      header: t("actions"),
      width: pixel(64),
      renderCell: (item) => <AppActions app={item} />
    }
  ];
  const collection = (members: AppSparse[], status: boolean, title: string) => (
    <ResourceCollection
      desktopList={
        view === "list" ? (
          <Table
            data={members}
            columns={columns}
            idKey="id"
            aria-label={title}
            plugins={{ sort: sortPlugin }}
          />
        ) : undefined
      }
    >
      {members.map((item) => (
        <AppTile key={item.id} app={item} showStatus={status} />
      ))}
    </ResourceCollection>
  );
  const groups = [true, false].map((published) => ({
    published,
    title: t(published ? "published" : "drafts"),
    members: filteredItems.filter((item) => item.published === published)
  }));
  if (sortConfig.sort[0]?.sortKey === "published") {
    const direction = sortConfig.sort[0].direction === "ascending" ? 1 : -1;
    groups.sort((a, b) => comparePublished(a.published, b.published) * direction);
  }

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
              <div className="flex flex-wrap items-center justify-between gap-3">
                {filterShown ? (
                  <ResourceFilterInput
                    value={filter}
                    onChange={setFilter}
                    label={t("space_filter_apps_label")}
                    placeholder={t("filter_apps_placeholder")}
                    resultCount={filteredItems.length}
                  />
                ) : null}
                <ResourceViewControls
                  view={view}
                  onViewChange={chooseView}
                  sortConfig={sortConfig}
                  options={[
                    { key: "name", label: t("name") },
                    ...(showStatus ? [{ key: "published" as const, label: t("status") }] : [])
                  ]}
                />
              </div>
              {filteredItems.length === 0 ? (
                <EmptyState
                  icon={<SearchX />}
                  title={t("no_results_found")}
                  headingLevel={3}
                  isCompact
                />
              ) : groupByStatus ? (
                <div className="flex flex-col gap-6">
                  {groups.map((group) => (
                    <ResourceGroup
                      key={String(group.published)}
                      title={group.title}
                      hidden={group.members.length === 0}
                    >
                      {collection(group.members, false, `${t("apps")} · ${group.title}`)}
                    </ResourceGroup>
                  ))}
                </div>
              ) : (
                collection(filteredItems, showStatus, t("apps"))
              )}
            </>
          )}
        </div>
      </AppActionScope>
    </RemovalFocusScope>
  );
}
