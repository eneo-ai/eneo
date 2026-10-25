"use client";

import { Button } from "@astryxdesign/core/Button";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import {
  pixel,
  proportional,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type TableSortComparator,
  type TableSortState
} from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type Ref } from "react";
import { QuietBanner } from "@/components/astryx/banner";
import { Table, type TableName } from "@/components/astryx/table";
import { EmptyState } from "@/components/composites/empty-state";
import { TableFrame } from "@/components/composites/table-frame";
import { useSpace } from "@/features/spaces/use-space";
import { useCollator } from "@astryxdesign/core/i18n";
import { useFocusRescue } from "@/lib/focus-rescue";
import type { IntegrationKnowledge } from "../knowledge";
import { RowsOrTable } from "../knowledge-list";
import { sourceRow } from "../knowledge-rows";
import { KnowledgeTableControls } from "../table-controls-ui";
import { IntegrationActions, WrapperActions } from "./actions";
import { SourceStateLabel, SourceUpdated, SyncProgress } from "./source-status";
import {
  countSourceFilters,
  isSyncActive,
  matchesSourceFilter,
  SOURCE_FILTERS,
  sourceContentsLabel,
  sourceHref,
  summarizeSource,
  waitingLabel,
  type IntegrationSource,
  type QueuedIds,
  type SourceFilter,
  type SourceState,
  type SourceSummary
} from "./sources";
import type { ProgressById } from "./sync-progress";
import { useAnnounceChange } from "@/lib/hooks/use-announce-change";
import { useSourceListAnnouncements } from "./use-sync-announcements";
import { VendorIcon } from "./vendor";

type SourceRow = {
  id: string;
  /** Sorted with the locale's collator (Astryx's default for `name`). */
  name: string;
  source: IntegrationSource;
  summary: SourceSummary;
};

type SourceSortKey = "name" | "documents" | "status" | "updated";

const DEFAULT_SORT: TableSortState<SourceSortKey> = [{ sortKey: "name", direction: "ascending" }];

// Whatever needs someone sorts first when sorting by status.
const STATE_ORDER: Record<SourceState, number> = {
  attention: 0,
  syncing: 1,
  queued: 2,
  never: 3,
  empty: 4,
  ok: 5
};

function time(value: string | null): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** A source that syncs shows "Updating now", the most recent there is. */
function updatedAt(summary: SourceSummary): number {
  if (summary.progress) return Number.POSITIVE_INFINITY;
  return time(summary.lastSyncedAt ?? summary.lastSyncAttemptedAt);
}

const COMPARATORS: Partial<Record<SourceSortKey, TableSortComparator<SourceRow>>> = {
  documents: (a, b) => a.summary.documentCount - b.summary.documentCount,
  status: (a, b) => STATE_ORDER[a.summary.state] - STATE_ORDER[b.summary.state],
  updated: (a, b) => {
    const [left, right] = [updatedAt(a.summary), updatedAt(b.summary)];
    return left === right ? 0 : left < right ? -1 : 1;
  }
};

function wrapperPermissions(items: IntegrationKnowledge[]) {
  const permissions = items[0]?.permissions ?? [];
  return { canEdit: permissions.includes("edit"), canDelete: permissions.includes("delete") };
}

function SourceNameCell({ source }: { source: IntegrationSource }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const [single] = source.items;
  const originalName =
    source.kind === "item" && single?.original_name && single.original_name !== single.name
      ? single.original_name
      : null;
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center">
        <VendorIcon type={source.integrationType} />
      </span>
      <span className="flex min-w-0 flex-col">
        <Link
          href={sourceHref(routeId, source)}
          className="text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 w-fit items-center font-semibold break-words hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
        >
          {source.name}
        </Link>
        <span className="text-ax-text-secondary text-xs">
          {originalName
            ? t("integration_source_original_name", { name: originalName })
            : sourceContentsLabel(source.items, t)}
        </span>
      </span>
    </span>
  );
}

/**
 * Progress while it syncs (and a warning if some folders failed); otherwise the
 * state, and the folders still waiting for their first sync.
 */
function SourceStatusCell({ row }: { row: SourceRow }) {
  const t = useTranslations();
  const { progress, failedItems } = row.summary;
  if (!progress) {
    const waiting = waitingLabel(row.summary, t);
    return (
      <span className="flex flex-col items-start gap-1">
        <SourceStateLabel state={row.summary.state} />
        {row.summary.state === "queued" && failedItems.length > 0 ? (
          <SourceStateLabel state="attention" />
        ) : null}
        {waiting ? <span className="text-ax-text-secondary text-xs">{waiting}</span> : null}
      </span>
    );
  }
  return (
    <div className="flex w-44 max-w-full flex-col gap-1.5">
      <SyncProgress progress={progress} name={row.name} />
      {failedItems.length > 0 ? <SourceStateLabel state="attention" /> : null}
    </div>
  );
}

/** Sources whose every failure is the organisation's refused SharePoint sign-in. */
function SignInStoppedBanner({
  rows,
  filter,
  onShowThem,
  ref
}: {
  rows: SourceRow[];
  filter: SourceFilter;
  onShowThem: () => void;
  ref: Ref<HTMLDivElement>;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const [first] = rows;
  const title = !first
    ? null
    : rows.length === 1
      ? t("integration_sources_attention_one")
      : t("integration_sources_attention_other", { count: rows.length });
  useAnnounceChange(title);
  if (!first || title === null) return null;
  const action =
    rows.length === 1 ? (
      <Button
        label={t("integration_sources_attention_open_one")}
        href={sourceHref(routeId, first.source, { tab: "problems" })}
        size="sm"
      />
    ) : filter !== "attention" ? (
      <Button label={t("integration_sources_attention_show_them")} size="sm" onClick={onShowThem} />
    ) : null;
  return (
    <QuietBanner
      ref={ref}
      // The focus target once "Show them" is gone (it hides itself).
      tabIndex={-1}
      status="error"
      title={title}
      description={t("integration_sources_attention_sign_in")}
      collapsible={false}
      endContent={action}
      className="focus-visible:outline-ring focus-visible:outline-2 focus-visible:outline-offset-2"
    />
  );
}

/** A source's menu: the wrapper's or its one item's. */
function SourceActions({ row }: { row: SourceRow }) {
  const [single] = row.source.items;
  return row.source.kind === "wrapper" ? (
    <WrapperActions
      wrapperId={row.source.id}
      wrapperName={row.name}
      items={row.source.items}
      {...wrapperPermissions(row.source.items)}
      syncActive={isSyncActive(row.summary)}
    />
  ) : single ? (
    <IntegrationActions item={single} syncActive={isSyncActive(row.summary)} />
  ) : null;
}

/** One table of sources, sortable by every column but the actions. */
function SourcesTable({
  rows,
  name,
  empty
}: {
  rows: SourceRow[];
  name: TableName;
  empty: React.ReactNode;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const { sortedData, sortConfig } = useTableSortableState<SourceRow, SourceSortKey>({
    data: rows,
    defaultSort: DEFAULT_SORT,
    comparators: COMPARATORS
  });
  const sortPlugin = useTableSortable<SourceRow, SourceSortKey>(sortConfig);

  const columns: TableColumn<SourceRow>[] = [
    {
      key: "name",
      header: t("integration_source_column_source"),
      width: proportional(1, { minWidth: 176 }),
      sortable: true,
      renderCell: (row) => <SourceNameCell source={row.source} />
    },
    {
      key: "documents",
      header: t("documents"),
      width: pixel(120),
      align: "end",
      sortable: true,
      renderCell: (row) => (
        <span className="tabular-nums">{format.number(row.summary.documentCount)}</span>
      )
    },
    {
      key: "status",
      header: t("status"),
      width: pixel(200),
      sortable: true,
      renderCell: (row) => <SourceStatusCell row={row} />
    },
    {
      key: "updated",
      header: t("integration_source_column_updated"),
      width: pixel(128),
      sortable: true,
      renderCell: (row) => <SourceUpdated summary={row.summary} />
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(72),
      align: "end",
      renderCell: (row) => <SourceActions row={row} />
    }
  ];

  return (
    <TableFrame>
      <Table
        data={sortedData}
        columns={columns}
        idKey="id"
        {...name}
        pinnedColumn="name"
        plugins={{ sort: sortPlugin }}
        emptyState={empty}
      />
    </TableFrame>
  );
}

/** Sources shown under one heading (an embedding model); `heading` null for an ungrouped list. */
export type SourceGroup = { key: string; heading: string | null; sources: IntegrationSource[] };

/**
 * The sources of a space (a wrapper of folders or a single item each): its
 * state or live progress, documents and last update, in one table or one per
 * group. The sign-in notice, the status filter and the search on a source's
 * or its folders' names sit once above every group; a group the filter
 * empties is left out, and a filter that matches nothing any more says so,
 * with a way back to every source. A source's sync starting, finishing or
 * being queued is announced. `name` names an ungrouped table.
 */
export function SourcesList({
  groups,
  progress,
  queued,
  progressLoaded,
  name
}: {
  groups: SourceGroup[];
  progress: ProgressById;
  /** Items whose sync was queued from here and that no worker has reported on yet. */
  queued: QueuedIds;
  /** Whether the progress poll has answered; nothing is announced before. */
  progressLoaded: boolean;
  name: TableName;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const collator = useCollator();
  // A search that matches no source of a group, said by its table or rows.
  const noResults = (
    <EmptyState title={t("no_results_found")} headingLevel={3} isCompact framed={false} />
  );
  const headingIds = useId();
  const bannerRef = useRef<HTMLDivElement>(null);
  const allFilterRef = useRef<HTMLButtonElement>(null);
  const chosenFilterRef = useRef<HTMLButtonElement>(null);
  const rescue = useFocusRescue();
  const [filter, setFilter] = useState<SourceFilter>("all");
  // Once a filter has been chosen the bar stays, so the pressed segment never vanishes under focus.
  const [filterUsed, setFilterUsed] = useState(false);
  const [query, setQuery] = useState("");

  const grouped = groups.map((group) => ({
    ...group,
    rows: group.sources.map((source): SourceRow => ({
      id: `${source.kind}-${source.id}`,
      name: source.name,
      source,
      summary: summarizeSource(source.items, progress, queued)
    }))
  }));
  const rows = grouped.flatMap((group) => group.rows);
  useSourceListAnnouncements(progressLoaded ? rows : null);
  const counts = countSourceFilters(rows.map((row) => row.summary));
  const needle = query.trim().toLocaleLowerCase();
  const isVisible = (row: SourceRow) =>
    matchesSourceFilter(row.summary, filter) &&
    (needle === "" ||
      [row.name, ...row.source.items.map((item) => item.name)].some((text) =>
        text.toLocaleLowerCase().includes(needle)
      ));
  const shown = grouped
    .map((group) => ({ ...group, rows: group.rows.filter(isVisible) }))
    .filter((group) => group.heading === null || group.rows.length > 0);
  const visibleCount = shown.reduce((sum, group) => sum + group.rows.length, 0);
  const signInStopped = rows.filter(
    (row) => row.summary.failedItems.length > 0 && row.summary.credentialsFailed
  );
  // The sources changed under the chosen filter (the failing one recovered, say).
  const noMatch = filter !== "all" && counts[filter] === 0;
  useAnnounceChange(noMatch ? t("integration_filter_no_match") : null);
  // The tables went, and focus with them if it was in one: the filter in use takes it.
  useEffect(() => {
    if (noMatch) rescue(chosenFilterRef.current);
  }, [noMatch, rescue]);

  function chooseFilter(next: SourceFilter) {
    setFilter(next);
    if (next !== "all") setFilterUsed(true);
  }

  function showAll() {
    setFilter("all");
    // The pressed button goes; the filter now in use takes focus.
    allFilterRef.current?.focus();
  }

  return (
    <div className="flex flex-col gap-4">
      <SignInStoppedBanner
        ref={bannerRef}
        rows={signInStopped}
        filter={filter}
        onShowThem={() => {
          chooseFilter("attention");
          rescue(bannerRef.current);
        }}
      />
      {rows.length > 1 || filterUsed ? (
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <SegmentedControl
            label={t("integration_filter_label")}
            value={filter}
            onChange={(value) => chooseFilter(value as SourceFilter)}
            size="sm"
          >
            {SOURCE_FILTERS.filter(
              (option) => option === "all" || option === filter || counts[option] > 0
            ).map((option) => (
              <SegmentedControlItem
                key={option}
                ref={
                  option === "all" ? allFilterRef : option === filter ? chosenFilterRef : undefined
                }
                value={option}
                label={t(`integration_filter_${option}`, { count: counts[option] })}
              />
            ))}
          </SegmentedControl>
          <KnowledgeTableControls
            filterValue={query}
            onFilterChange={setQuery}
            filterLabel={t("space_filter_integrations_label")}
            filterPlaceholder={t("ui_filter_items", { resourceName: t("resource_integrations") })}
            resultCount={visibleCount}
          />
        </div>
      ) : null}
      {noMatch ? (
        <div className="flex flex-col items-start gap-3 py-6">
          <p className="text-ax-text-secondary text-sm">{t("integration_filter_no_match")}</p>
          <Button label={t("integration_filter_show_all")} size="sm" onClick={showAll} />
        </div>
      ) : shown.length === 0 ? (
        // Under the group headings (h3) and the page's "Kunskap" (h2).
        <EmptyState title={t("no_results_found")} headingLevel={3} isCompact />
      ) : (
        shown.map((group) => {
          const headingId = group.heading === null ? null : `${headingIds}-${group.key}`;
          return (
            <div key={group.key} className="flex flex-col gap-2">
              {headingId ? (
                <h3 id={headingId} className="text-ax-text-secondary text-sm font-semibold">
                  {group.heading}
                </h3>
              ) : null}
              <RowsOrTable
                items={[...group.rows]
                  .sort((a, b) => collator.compare(a.name, b.name))
                  .map((row) => ({
                    row: sourceRow(row.source, row.summary, routeId),
                    actions: <SourceActions row={row} />
                  }))}
                name={headingId ? { "aria-labelledby": headingId } : name}
                empty={noResults}
              >
                <SourcesTable
                  rows={group.rows}
                  name={headingId ? { "aria-labelledby": headingId } : name}
                  empty={noResults}
                />
              </RowsOrTable>
            </div>
          );
        })
      )}
    </div>
  );
}
