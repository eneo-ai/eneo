"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { useCollator } from "@astryxdesign/core/i18n";
import { Link as AstryxLink } from "@astryxdesign/core/Link";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import {
  pixel,
  proportional,
  Table,
  useTableSelection,
  useTableSelectionState,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type UseTableSortableConfig
} from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderInput, Globe, Pencil, RefreshCw, SearchX, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import type { StatusTone } from "@/components/composites/status-label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { daysSince } from "@/lib/format";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { toast } from "@/lib/toast";
import { useJobs } from "@/features/jobs/use-jobs";
import { ClientTime } from "@/components/composites/client-time";
import { useRemovalMutation } from "@/features/spaces/removal";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { useSpace } from "@/features/spaces/use-space";
import { embeddingModelsInUse, formatWebsiteName, type Website } from "./knowledge";
import { WEBSITE_DEFAULT_SORT, websiteComparators, type WebsiteSortKey } from "./knowledge-sort";
import { MoveResourceDialog } from "./move-dialog";
import { NoCreatePermissionInfo } from "./no-create-permission-info";
import { filterWebsites } from "./table-controls";
import { KnowledgeLabel, KnowledgeNameCell, KnowledgeTableControls } from "./table-controls-ui";
import { WebsiteDialog } from "./website-dialog";
import {
  crawlFailuresText,
  isSkippedCrawl,
  nextCrawlAt,
  STALE_SYNC_DAYS,
  websiteStatus,
  websiteSyncedAt
} from "./website-status";

/** The latest crawl's state, with why it was skipped or failed, or what failed. */
function WebsiteStatusCell({ website }: { website: Website }) {
  const t = useTranslations();
  const status = websiteStatus(website);
  const crawl = website.latest_crawl;

  let detail: string | undefined;
  if (isSkippedCrawl(crawl)) {
    detail = t("crawl_skipped_duplicate");
  } else if (status.tone === "warning" && crawl) {
    detail = crawlFailuresText(t, crawl);
  } else if (status.tone === "error") {
    detail = crawl?.result_location ?? undefined;
  }

  return (
    <KnowledgeLabel
      tone={status.tone}
      label={t(status.labelKey)}
      detail={detail}
      isPulsing={status.isPulsing}
    />
  );
}

/**
 * When the latest crawl completed; a sync older than ten days is flagged.
 * The age depends on the viewer's clock, so it is judged after hydration.
 */
function WebsiteSyncedCell({ website }: { website: Website }) {
  const t = useTranslations();
  const hydrated = useHydrated();
  const syncedAt = websiteSyncedAt(website);
  if (!syncedAt) return "—";
  const isStale = hydrated && daysSince(syncedAt) >= STALE_SYNC_DAYS;
  return (
    <span className="flex flex-col items-start gap-0.5">
      <ClientTime value={syncedAt} format="date" />
      {isStale ? (
        <KnowledgeLabel tone="warning" label={t("space_sync_stale", { days: STALE_SYNC_DAYS })} />
      ) : null}
    </span>
  );
}

const INTERVAL_LABELS: Record<Website["update_interval"], { key: string; tone: StatusTone }> = {
  daily: { key: "every_day", tone: "success" },
  every_other_day: { key: "every_other_day", tone: "success" },
  weekly: { key: "weekly", tone: "success" },
  never: { key: "never", tone: "neutral" }
};

/** Automatic re-crawl interval: on (green) or off (grey), and when the next crawl runs. */
function WebsiteIntervalLabel({ website }: { website: Website }) {
  const t = useTranslations();
  const item = INTERVAL_LABELS[website.update_interval] ?? {
    key: "not_found",
    tone: "error" as const
  };
  const next = nextCrawlAt(website);
  const detail =
    next === undefined
      ? undefined
      : next === null
        ? t("next_crawl_after_first_run")
        : t.rich("space_next_crawl", {
            time: () => <ClientTime value={next} format="date" />
          });
  return <KnowledgeLabel tone={item.tone} label={t(item.key)} detail={detail} />;
}

/** Row menu for a website: edit, move to another space, delete. */
export function WebsiteActions({ website }: { website: Website }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const canDelete = website.permissions?.includes("delete") ?? false;
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const deleteWebsite = useRemovalMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/websites/{id}/", { params: { path: { id: website.id } } })),
    refresh: invalidate,
    onRemoved: () => setShowDelete(false)
  });

  const moveWebsite = useRemovalMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/websites/{id}/transfer/", {
          params: { path: { id: website.id } },
          body: { target_space_id: targetSpaceId }
        })
      ),
    refresh: invalidate,
    onRemoved: () => setShowMove(false)
  });

  const websiteDisplay = website.name ? `${website.name} (${website.url})` : website.url;

  const items: DropdownMenuOption[] = [
    { label: t("edit"), icon: <Pencil aria-hidden="true" />, onClick: () => setShowEdit(true) },
    ...(canDelete && !space.organization
      ? [
          {
            label: t("move"),
            icon: <FolderInput aria-hidden="true" />,
            onClick: () => setShowMove(true)
          }
        ]
      : []),
    ...(canDelete
      ? [
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive" as const,
            onClick: () => setShowDelete(true)
          }
        ]
      : [])
  ];

  return (
    <>
      <MoreMenu
        label={t("space_more_actions_for", { name: formatWebsiteName(website) })}
        items={items}
        alignment="end"
      />
      {showEdit && <WebsiteDialog website={website} open={showEdit} onOpenChange={setShowEdit} />}
      <MoveResourceDialog
        open={showMove}
        onOpenChange={setShowMove}
        title={t("move_website")}
        hint={t("move_website_hint")}
        confirmLabel={t("move_website")}
        pending={moveWebsite.isPending}
        onMove={(targetSpaceId) => moveWebsite.mutate(targetSpaceId)}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_crawl")}
        description={`${t("confirm_delete_crawl_start")} ${websiteDisplay}${t("confirm_delete_crawl_end")}`}
        confirmLabel={deleteWebsite.isPending ? t("deleting") : t("delete")}
        pending={deleteWebsite.isPending}
        onConfirm={() => deleteWebsite.mutate()}
      />
    </>
  );
}

/**
 * One embedding model's websites. Sorting is shared across the groups; the
 * checkboxes (for bulk sync) select into one set, the header one selects this
 * group's rows. `labelledBy` names the table: the model heading when grouped
 * (which tells the groups' "select all" checkboxes apart), else the tab.
 */
function WebsitesTable({
  websites,
  sortConfig,
  selectable,
  selectedKeys,
  setSelectedKeys,
  labelledBy
}: {
  websites: Website[];
  sortConfig: UseTableSortableConfig<WebsiteSortKey>;
  selectable: boolean;
  selectedKeys: Set<string>;
  setSelectedKeys: Dispatch<SetStateAction<Set<string>>>;
  labelledBy: string;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const sortPlugin = useTableSortable<Website, WebsiteSortKey>(sortConfig);
  const { selectionConfig } = useTableSelectionState<Website>({
    data: websites,
    idKey: "id",
    selectedKeys,
    setSelectedKeys
  });
  const selectionPlugin = useTableSelection<Website>({
    ...selectionConfig,
    getRowLabel: formatWebsiteName,
    hasRowHighlight: false
  });

  const columns: TableColumn<Website>[] = [
    {
      key: "name",
      header: t("website"),
      width: proportional(3),
      sortable: true,
      renderCell: (website) => (
        <KnowledgeNameCell
          icon={Globe}
          href={`/spaces/${routeId}/knowledge/websites/${website.id}`}
        >
          <span className="break-all">{formatWebsiteName(website)}</span>
        </KnowledgeNameCell>
      )
    },
    {
      key: "link",
      header: t("link"),
      width: proportional(1),
      renderCell: (website) => (
        <AstryxLink href={website.url} isExternalLink color="secondary">
          {t("go_to_website")}
        </AstryxLink>
      )
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(1),
      sortable: true,
      renderCell: (website) => <WebsiteStatusCell website={website} />
    },
    {
      key: "synced",
      header: t("space_synced_column"),
      width: proportional(1),
      sortable: true,
      renderCell: (website) => <WebsiteSyncedCell website={website} />
    },
    {
      key: "interval",
      header: t("auto_updates"),
      width: proportional(1),
      sortable: true,
      renderCell: (website) => <WebsiteIntervalLabel website={website} />
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (website) => <WebsiteActions website={website} />
    }
  ];

  return (
    <SpaceTableFrame>
      <Table
        data={websites}
        columns={columns}
        idKey="id"
        aria-labelledby={labelledBy}
        plugins={
          selectable ? { sort: sortPlugin, selection: selectionPlugin } : { sort: sortPlugin }
        }
      />
    </SpaceTableFrame>
  );
}

/** The websites tab; `labelledBy` is the tab, which names an ungrouped table. */
export function WebsitesTab({ canCreate, labelledBy }: { canCreate: boolean; labelledBy: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const { trackJob } = useJobs();
  const collator = useCollator();
  const groupId = useId();
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [showCreate, setShowCreate] = useState(false);
  const [filter, setFilter] = useState("");

  const websites = space.knowledge.websites.items.filter(
    (website) => website.space_id === space.id
  );
  const visibleWebsites = filterWebsites(websites, filter);
  // Only what is on screen counts as selected: rows the filter hides and
  // websites that were deleted meanwhile are never synced.
  const selectedIds = visibleWebsites
    .filter((website) => selected.has(website.id))
    .map((website) => website.id);
  const comparators = useMemo(() => websiteComparators(collator.compare), [collator]);
  // Sorted by the column headers; one sort order across the model groups.
  const { sortedData, sortConfig } = useTableSortableState<Website, WebsiteSortKey>({
    data: visibleWebsites,
    defaultSort: WEBSITE_DEFAULT_SORT,
    comparators
  });
  const models = embeddingModelsInUse(visibleWebsites, space.embedding_models);
  const grouped =
    models.length > 1 ||
    space.embedding_models.length > 1 ||
    models.some((model) => !model.inSpace);

  const bulkRecrawl = useMutation({
    mutationFn: (websiteIds: string[]) =>
      unwrap(browserApi.POST("/api/v1/websites/bulk/run/", { body: { website_ids: websiteIds } })),
    onSuccess: (result) => {
      if (result.failed > 0) {
        const details = result.errors
          .map((entry) => entry.error)
          .filter(Boolean)
          .join(", ");
        toast.error(
          t("websites_bulk_recrawl_failed", { queued: result.queued, failed: result.failed }),
          { description: details || undefined }
        );
      } else {
        toast.success(t("websites_bulk_recrawl_queued", { count: result.queued }));
      }
      setSelected(new Set());
      trackJob();
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
    },
    onError: (error) => toastApiError(error, t)
  });

  const connectButton = (
    <AstryxButton
      label={t("connect_website")}
      variant="primary"
      onClick={() => setShowCreate(true)}
    />
  );
  const createDialog = showCreate ? (
    <WebsiteDialog open={showCreate} onOpenChange={setShowCreate} />
  ) : null;

  // Nothing to filter yet: the empty state carries the one create button.
  if (websites.length === 0) {
    return (
      <>
        <EmptyState
          icon={<Globe />}
          title={t("space_websites_empty_title")}
          description={t("space_websites_empty_description")}
          headingLevel={3}
          actions={
            canCreate ? (
              connectButton
            ) : (
              <NoCreatePermissionInfo resourceType={t("resource_websites")} />
            )
          }
        />
        {createDialog}
      </>
    );
  }

  const action = (
    <>
      {canCreate && selectedIds.length > 0 ? (
        <AstryxButton
          label={
            bulkRecrawl.isPending ? t("syncing") : t("sync_selected", { count: selectedIds.length })
          }
          variant="primary"
          icon={<RefreshCw aria-hidden="true" />}
          isDisabled={bulkRecrawl.isPending}
          onClick={() => bulkRecrawl.mutate(selectedIds)}
        />
      ) : null}
      {canCreate && selectedIds.length === 0 ? connectButton : null}
      {!canCreate ? <NoCreatePermissionInfo resourceType={t("resource_websites")} /> : null}
      {createDialog}
    </>
  );

  const toolbar = (
    <KnowledgeTableControls
      filterValue={filter}
      onFilterChange={setFilter}
      filterLabel={t("space_filter_websites_label")}
      filterPlaceholder={t("ui_filter_items", { resourceName: t("resource_websites") })}
      resultCount={visibleWebsites.length}
    >
      {action}
    </KnowledgeTableControls>
  );

  if (visibleWebsites.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {toolbar}
        <EmptyState
          icon={<SearchX />}
          title={t("ui_no_items_matching", { resourceNamePlural: t("resource_websites") })}
          headingLevel={3}
          isCompact
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {toolbar}
      {(grouped ? models : [null]).map((model) => {
        const rows = model
          ? sortedData.filter((website) => website.embedding_model.id === model.id)
          : sortedData;
        const headingId = model ? `${groupId}-${model.id}` : undefined;
        return (
          <div key={model?.id ?? "all"} className="flex flex-col gap-2">
            {model && (
              <h3 id={headingId} className="text-ax-text-secondary text-sm font-semibold">
                {model.name}
                {model.inSpace ? "" : ` (${t("disabled")})`}
              </h3>
            )}
            <WebsitesTable
              websites={rows}
              sortConfig={sortConfig}
              selectable={canCreate}
              selectedKeys={selected}
              setSelectedKeys={setSelected}
              labelledBy={headingId ?? labelledBy}
            />
          </div>
        );
      })}
    </div>
  );
}
