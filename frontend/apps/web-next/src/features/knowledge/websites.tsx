"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { useCollator } from "@astryxdesign/core/i18n";
import { Link as AstryxLink } from "@astryxdesign/core/Link";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import {
  pixel,
  proportional,
  TableSelectionToolbar,
  useTableSelection,
  useTableSelectionState,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type TableSelectionState,
  type UseTableSortableConfig
} from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderInput, Globe, Pencil, RefreshCw, SearchX, Square, Trash2 } from "lucide-react";
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
import { spaceQueryOptions } from "@/features/spaces/space";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { useSpace } from "@/features/spaces/use-space";
import { embeddingModelsInUse, formatWebsiteName, type CrawlRun, type Website } from "./knowledge";
import { WEBSITE_DEFAULT_SORT, websiteComparators, type WebsiteSortKey } from "./knowledge-sort";
import { MoveResourceDialog } from "./move-dialog";
import { NoCreatePermissionInfo } from "./no-create-permission-info";
import { filterWebsites } from "./table-controls";
import { KnowledgeLabel, KnowledgeNameCell, KnowledgeTableControls } from "./table-controls-ui";
import { WebsiteDialog } from "./website-dialog";
import {
  bulkDeletionWaitsForCrawlerCleanup,
  bulkFailureWebsiteIds,
  deleteWebsiteBatches,
  runWebsiteBatches,
  stopWebsiteBatches,
  type BulkDeleteSummary,
  type BulkStopSummary
} from "./bulk-website-actions";
import { CrawlRunDetailsDialog } from "./crawl-run-details";
import { canRequestCrawlStop, type CrawlFailureKind } from "./crawl-run-state";
import { CrawlFailureActions, CrawlRunStatusLabel } from "./crawl-run-ui";
import { isActiveCrawl, nextCrawlAt, STALE_SYNC_DAYS, websiteSyncedAt } from "./website-status";

const ACTIVE_CRAWL_REFRESH_MS = 2_000;
const IDLE_WEBSITE_REFRESH_MS = 30_000;

/** Which run's failures to show, and of which kind. */
type FailureSelection = { run: CrawlRun; kind: CrawlFailureKind | null };

/** The latest run's state, with links to what failed in it. */
function WebsiteStatusCell({
  website,
  onShowFailures
}: {
  website: Website;
  onShowFailures: (selection: FailureSelection) => void;
}) {
  const t = useTranslations();
  const run = website.latest_crawl;
  if (!run) return <KnowledgeLabel tone="neutral" label={t("website_not_yet_crawled")} />;
  return (
    <span className="flex flex-col items-start gap-1">
      <CrawlRunStatusLabel run={run} />
      <CrawlFailureActions run={run} onSelect={(kind) => onShowFailures({ run, kind })} />
    </span>
  );
}

/**
 * When the website's content was last indexed; older than ten days is
 * flagged. The age depends on the viewer's clock, so it is judged after
 * hydration.
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

/**
 * Why a single website could not be removed, as the Svelte app says it: the
 * crawler stops its run or finishes cleaning up first, or it was already gone.
 */
function deleteOutcomeToast(
  result: BulkDeleteSummary,
  t: (key: string, values?: Record<string, string | number>) => string
) {
  if (result.deleted === 1) {
    toast.success(t("websites_removed", { count: 1 }));
  } else if (result.errors.some((error) => error.error === "crawl_stop_requested")) {
    toast.info(t("website_remove_stopping"));
  } else if (result.errors.some((error) => error.error === "crawl_cleanup_pending")) {
    toast.info(t("website_remove_cleanup_pending"));
  } else if (result.notFound === 1) {
    toast.info(t("websites_already_removed"));
  } else {
    toast.error(t("bulk_website_remove_failed"));
  }
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

  // The bulk endpoint also removes one website, and says when the crawler
  // has to stop its run first (the website then stays until removed again).
  const deleteWebsite = useRemovalMutation({
    mutationFn: () =>
      deleteWebsiteBatches([website.id], (websiteIds) =>
        unwrap(
          browserApi.POST("/api/v1/websites/bulk/delete/", { body: { website_ids: websiteIds } })
        )
      ),
    refresh: invalidate,
    onRemoved: (result) => {
      deleteOutcomeToast(result, t);
      setShowDelete(false);
    }
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
        title={t("remove_website_title")}
        description={`${t("remove_website_description")} ${websiteDisplay}`}
        confirmLabel={deleteWebsite.isPending ? t("deleting") : t("remove_website_confirm")}
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
  const [failures, setFailures] = useState<FailureSelection | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
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
      renderCell: (website) => (
        <WebsiteStatusCell
          website={website}
          onShowFailures={(selection) => {
            setFailures(selection);
            setDetailsOpen(true);
          }}
        />
      )
    },
    {
      key: "synced",
      header: t("website_last_indexed"),
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
    <>
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
      {failures ? (
        <CrawlRunDetailsDialog
          run={failures.run}
          initialKind={failures.kind}
          isOpen={detailsOpen}
          onOpenChange={setDetailsOpen}
        />
      ) : null}
    </>
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

  // Watch the same space query used by useSpace. An active crawl gets quick
  // updates; the slower idle poll also finds crawls started by a schedule or
  // another user, even when this browser never registered their job.
  useQuery({
    ...spaceQueryOptions(browserApi, routeId),
    refetchInterval: (query) =>
      query.state.data?.knowledge.websites.items.some((website) =>
        isActiveCrawl(website.latest_crawl)
      )
        ? ACTIVE_CRAWL_REFRESH_MS
        : IDLE_WEBSITE_REFRESH_MS
  });

  const websites = space.knowledge.websites.items.filter(
    (website) => website.space_id === space.id
  );
  const visibleWebsites = filterWebsites(websites, filter);
  // Only what is on screen counts as selected: rows the filter hides and
  // websites that were deleted meanwhile are never synced.
  const selectedIds = visibleWebsites
    .filter((website) => selected.has(website.id))
    .map((website) => website.id);
  // One selection across the per-model tables; each table's own
  // useTableSelectionState reads and writes this same set.
  const selectionState: TableSelectionState = {
    selectedKeys: selected,
    selectedCount: selected.size,
    hasSelection: selected.size > 0,
    clearSelection: () => setSelected(new Set())
  };
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

  const stoppableIds = websites
    .filter((website) => website.latest_crawl && canRequestCrawlStop(website.latest_crawl))
    .map((website) => website.id);
  const selectedStoppableIds = stoppableIds.filter((id) => selected.has(id));
  const selectedDeletableIds = visibleWebsites
    .filter((website) => selected.has(website.id) && website.permissions?.includes("delete"))
    .map((website) => website.id);
  const [stopTargets, setStopTargets] = useState<string[] | null>(null);
  const [deleteTargets, setDeleteTargets] = useState<string[] | null>(null);
  const refreshWebsites = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  // A selection is sent in batches (bulk-website-actions.ts); the websites
  // that could not be acted on stay selected, so the user can retry them.
  const bulkRecrawl = useMutation({
    mutationFn: (websiteIds: string[]) =>
      runWebsiteBatches(websiteIds, (ids) =>
        unwrap(browserApi.POST("/api/v1/websites/bulk/run/", { body: { website_ids: ids } }))
      ),
    onSuccess: (result) => {
      if (result.failed > 0) {
        toast.error(
          result.queued > 0
            ? t("bulk_crawl_partial", { queued: result.queued, failed: result.failed })
            : t("bulk_crawl_failed")
        );
        setSelected(new Set(bulkFailureWebsiteIds(result.errors)));
      } else {
        toast.success(t("bulk_crawl_started", { count: result.queued, total: result.total }));
        setSelected(new Set());
      }
      trackJob();
      void refreshWebsites();
    },
    onError: (error) => toastApiError(error, t)
  });

  const bulkStop = useMutation({
    mutationFn: (websiteIds: string[]) =>
      stopWebsiteBatches(websiteIds, (ids) =>
        unwrap(browserApi.POST("/api/v1/websites/bulk/stop/", { body: { website_ids: ids } }))
      ),
    onSuccess: (result: BulkStopSummary) => {
      if (result.failed > 0) {
        toast.error(
          result.stopped > 0
            ? t("crawls_stop_partial", { stopped: result.stopped, failed: result.failed })
            : t("bulk_crawl_stop_failed")
        );
        setSelected(new Set(bulkFailureWebsiteIds(result.errors)));
      } else {
        if (result.stopped > 0)
          toast.success(t("crawls_stop_requested", { count: result.stopped }));
        setSelected(new Set());
      }
      setStopTargets(null);
      void refreshWebsites();
    },
    onError: (error) => toastApiError(error, t)
  });

  const bulkDelete = useRemovalMutation({
    mutationFn: (websiteIds: string[]) =>
      deleteWebsiteBatches(websiteIds, (ids) =>
        unwrap(browserApi.POST("/api/v1/websites/bulk/delete/", { body: { website_ids: ids } }))
      ),
    refresh: refreshWebsites,
    onRemoved: (result, websiteIds) => {
      if (result.failed > 0) {
        if (bulkDeletionWaitsForCrawlerCleanup(result.errors)) {
          const cleanupPending = result.errors.some(
            (error) => error.error === "crawl_cleanup_pending"
          );
          toast.info(
            cleanupPending
              ? t("websites_remove_cleanup_pending")
              : result.deleted > 0
                ? t("websites_remove_partial_stopping")
                : t("websites_remove_stopping")
          );
        } else {
          toast.error(
            result.deleted > 0
              ? t("websites_remove_partial", { deleted: result.deleted, failed: result.failed })
              : t("bulk_website_remove_failed")
          );
        }
        const failedIds = bulkFailureWebsiteIds(result.errors);
        setSelected(new Set(failedIds.length > 0 ? failedIds : websiteIds));
      } else {
        if (result.deleted > 0) toast.success(t("websites_removed", { count: result.deleted }));
        else toast.info(t("websites_already_removed"));
        setSelected(new Set());
      }
      setDeleteTargets(null);
    }
  });
  const bulkPending = bulkRecrawl.isPending || bulkStop.isPending || bulkDelete.isPending;

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

  // Busy buttons stay enabled so they keep focus; a second press is ignored.
  const stopButton = (ids: string[], labelKey: "stop_selected_crawls" | "stop_all_crawls") => (
    <AstryxButton
      label={bulkStop.isPending ? t("stopping_crawls") : t(labelKey, { count: ids.length })}
      icon={<Square aria-hidden="true" />}
      isLoading={bulkStop.isPending}
      isInterruptible
      onClick={() => {
        if (!bulkPending) setStopTargets(ids);
      }}
    />
  );
  // Astryx's selection toolbar owns the count and "clear selection"; the
  // actions for the selected rows are ours. Only visible rows count as
  // selected (see selectedIds), so the toolbar follows that count.
  const selectionToolbar =
    selectedIds.length > 0 ? (
      <TableSelectionToolbar
        selection={selectionState}
        label={t("websites_bulk_actions")}
        clearLabel={t("clear_selection")}
        renderSelectionLabel={() => t("websites_selected_count", { count: selectedIds.length })}
        startContent={
          <>
            {canCreate && selectedStoppableIds.length > 0
              ? stopButton(selectedStoppableIds, "stop_selected_crawls")
              : null}
            {selectedDeletableIds.length > 0 ? (
              <AstryxButton
                variant="destructive"
                label={
                  bulkDelete.isPending
                    ? t("removing_websites")
                    : t("remove_selected_websites", { count: selectedDeletableIds.length })
                }
                icon={<Trash2 aria-hidden="true" />}
                isLoading={bulkDelete.isPending}
                isInterruptible
                onClick={() => {
                  if (!bulkPending) setDeleteTargets(selectedDeletableIds);
                }}
              />
            ) : null}
            {canCreate ? (
              <AstryxButton
                label={
                  bulkRecrawl.isPending
                    ? t("syncing")
                    : t("sync_selected", { count: selectedIds.length })
                }
                variant="primary"
                icon={<RefreshCw aria-hidden="true" />}
                isLoading={bulkRecrawl.isPending}
                isInterruptible
                onClick={() => {
                  if (!bulkPending) bulkRecrawl.mutate(selectedIds);
                }}
              />
            ) : null}
          </>
        }
      />
    ) : null;
  const action = (
    <>
      {canCreate && stoppableIds.length > 0 ? stopButton(stoppableIds, "stop_all_crawls") : null}
      {canCreate ? connectButton : null}
      {!canCreate ? <NoCreatePermissionInfo resourceType={t("resource_websites")} /> : null}
      {createDialog}
      <ConfirmDialogControlled
        open={stopTargets !== null}
        onOpenChange={(open) => {
          if (!open) setStopTargets(null);
        }}
        title={t("stop_crawls_title", { count: stopTargets?.length ?? 0 })}
        description={t("stop_crawls_description")}
        confirmLabel={bulkStop.isPending ? t("stopping_crawls") : t("stop_crawl")}
        pending={bulkStop.isPending}
        onConfirm={() => {
          if (stopTargets) bulkStop.mutate(stopTargets);
        }}
      />
      <ConfirmDialogControlled
        open={deleteTargets !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTargets(null);
        }}
        title={t("remove_websites_title", { count: deleteTargets?.length ?? 0 })}
        description={t("remove_websites_description")}
        confirmLabel={bulkDelete.isPending ? t("removing_websites") : t("remove_websites_confirm")}
        pending={bulkDelete.isPending}
        onConfirm={() => {
          if (deleteTargets) bulkDelete.mutate(deleteTargets);
        }}
      />
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
      {selectionToolbar}
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
