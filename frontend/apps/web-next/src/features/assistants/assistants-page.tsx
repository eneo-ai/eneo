"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { Bot, SearchX } from "lucide-react";
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
import { RemovalFocusScope } from "@/features/spaces/removal";
import { filterSpaceResources } from "@/features/spaces/resource-filter";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { useSpace } from "@/features/spaces/use-space";
import { chatPartnerHref, spaceChatItems, type ChatAppItem } from "./assistants";
import { CreateChatAppMenu } from "./create-menu";
import { ChatAppActions } from "./actions";
import { ChatAppTile } from "./tile";

export function AssistantsPage() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const collator = useCollator();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [filter, setFilter] = useState("");

  const items = useMemo(() => spaceChatItems(space, collator.compare), [space, collator]);
  const matchedItems = useMemo(() => filterSpaceResources(items, filter), [items, filter]);
  const { view, chooseView } = useResourceView("assistants", "cards");
  const comparePublished = useCallback(
    (a: boolean, b: boolean) =>
      collator.compare(t(a ? "published" : "draft"), t(b ? "published" : "draft")),
    [collator, t]
  );
  const comparators = useMemo<Record<"name" | "published", TableSortComparator<ChatAppItem>>>(
    () => ({
      name: (a, b) => collator.compare(a.name, b.name),
      published: (a, b) => comparePublished(Boolean(a.published), Boolean(b.published))
    }),
    [collator, comparePublished]
  );
  const { sortedData: filteredItems, sortConfig } = useTableSortableState<
    ChatAppItem,
    "name" | "published"
  >({
    data: matchedItems,
    comparators,
    defaultSort: [{ sortKey: "name", direction: "ascending" }],
    allowUnsortedState: false
  });
  const sortPlugin = useTableSortable<ChatAppItem, "name" | "published">(sortConfig);
  const showStatus = !space.personal;
  const groupByStatus = can("publish", "assistant");
  const canCreate = can("create", "assistant");

  const columns: TableColumn<ChatAppItem>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(2),
      sortable: true,
      renderCell: (item) => (
        <Link href={chatPartnerHref(routeId, item)} className="font-medium hover:underline">
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
            renderCell: (item: ChatAppItem) => (
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
      renderCell: (item) => <ChatAppActions item={item} />
    }
  ];
  const collection = (members: ChatAppItem[], status: boolean, title: string) => (
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
        <ChatAppTile key={item.id} item={item} showStatus={status} />
      ))}
    </ResourceCollection>
  );
  const groups = [true, false].map((published) => ({
    published,
    title: t(published ? "published" : "drafts"),
    members: filteredItems.filter((item) => Boolean(item.published) === published)
  }));
  if (sortConfig.sort[0]?.sortKey === "published") {
    const direction = sortConfig.sort[0].direction === "ascending" ? 1 : -1;
    groups.sort((a, b) => comparePublished(Boolean(a.published), Boolean(b.published)) * direction);
  }

  return (
    <RemovalFocusScope target={headingRef}>
      <div className="flex w-full flex-col gap-6">
        <PageHeader
          headingLevel={2}
          headingRef={headingRef}
          title={t("assistants")}
          actions={canCreate && items.length > 0 ? <CreateChatAppMenu /> : undefined}
        />
        {items.length === 0 ? (
          <EmptyState
            icon={<Bot />}
            hue={AREA_HUES.assistants}
            title={t("space_assistants_empty_title")}
            description={t("space_assistants_empty_description")}
            headingLevel={3}
            actions={canCreate ? <CreateChatAppMenu /> : undefined}
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <ResourceFilterInput
                value={filter}
                onChange={setFilter}
                label={t("space_filter_assistants_label")}
                placeholder={t("filter_assistants_placeholder")}
                resultCount={filteredItems.length}
              />
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
                    {collection(group.members, false, `${t("assistants")} · ${group.title}`)}
                  </ResourceGroup>
                ))}
              </div>
            ) : (
              collection(filteredItems, showStatus, t("assistants"))
            )}
          </>
        )}
      </div>
    </RemovalFocusScope>
  );
}
