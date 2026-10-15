"use client";

import { Banner } from "@astryxdesign/core/Banner";
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
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Table } from "@/components/astryx/table";
import { EmptyState } from "@/components/composites/empty-state";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { useSpace } from "@/features/spaces/use-space";
import type { IntegrationKnowledge } from "../knowledge";
import { KnowledgeTableControls } from "../table-controls-ui";
import { IntegrationActions, WrapperActions } from "./actions";
import { SourceStateLabel, SourceUpdated, SyncProgress } from "./source-status";
import {
  countSourceFilters,
  matchesSourceFilter,
  SOURCE_FILTERS,
  sourceContentsLabel,
  sourceHref,
  summarizeSource,
  type IntegrationSource,
  type SourceFilter,
  type SourceState,
  type SourceSummary
} from "./sources";
import type { ProgressById } from "./sync-progress";
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
  never: 2,
  empty: 3,
  ok: 4
};

function time(value: string | null): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

const COMPARATORS: Partial<Record<SourceSortKey, TableSortComparator<SourceRow>>> = {
  documents: (a, b) => a.summary.documentCount - b.summary.documentCount,
  status: (a, b) => STATE_ORDER[a.summary.state] - STATE_ORDER[b.summary.state],
  updated: (a, b) => time(a.summary.lastSyncedAt) - time(b.summary.lastSyncedAt)
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

/** Progress while it syncs (and a warning if some folders failed); otherwise the state alone. */
function SourceStatusCell({ row }: { row: SourceRow }) {
  const { progress, failedItems } = row.summary;
  if (!progress) return <SourceStateLabel state={row.summary.state} />;
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
  onShowThem
}: {
  rows: SourceRow[];
  filter: SourceFilter;
  onShowThem: () => void;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const [first] = rows;
  if (!first) return null;
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
    <Banner
      status="error"
      title={
        rows.length === 1
          ? t("integration_sources_attention_one")
          : t("integration_sources_attention_other", { count: rows.length })
      }
      description={t("integration_sources_attention_sign_in")}
      collapsible={false}
      endContent={action}
    />
  );
}

/**
 * One row per source (a wrapper of folders or a single item): its state or
 * live progress, documents and last update. Filters by state and by a search
 * on the source's or its folders' names; sorts by every column but actions.
 */
export function SourcesTable({
  sources,
  progress,
  labelledBy
}: {
  sources: IntegrationSource[];
  progress: ProgressById;
  labelledBy: string;
}) {
  const t = useTranslations();
  const [filter, setFilter] = useState<SourceFilter>("all");
  const [query, setQuery] = useState("");

  const rows: SourceRow[] = sources.map((source) => ({
    id: `${source.kind}-${source.id}`,
    name: source.name,
    source,
    summary: summarizeSource(source.items, progress)
  }));
  const counts = countSourceFilters(rows.map((row) => row.summary));
  const needle = query.trim().toLocaleLowerCase();
  const visible = rows.filter(
    (row) =>
      matchesSourceFilter(row.summary, filter) &&
      (needle === "" ||
        [row.name, ...row.source.items.map((item) => item.name)].some((text) =>
          text.toLocaleLowerCase().includes(needle)
        ))
  );
  const signInStopped = rows.filter(
    (row) => row.summary.failedItems.length > 0 && row.summary.credentialsFailed
  );

  const { sortedData, sortConfig } = useTableSortableState<SourceRow, SourceSortKey>({
    data: visible,
    defaultSort: DEFAULT_SORT,
    comparators: COMPARATORS
  });
  const sortPlugin = useTableSortable<SourceRow, SourceSortKey>(sortConfig);

  const columns: TableColumn<SourceRow>[] = [
    {
      key: "name",
      header: t("integration_source_column_source"),
      width: proportional(3),
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
        <span className="tabular-nums">{row.summary.documentCount.toLocaleString()}</span>
      )
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(2),
      sortable: true,
      renderCell: (row) => <SourceStatusCell row={row} />
    },
    {
      key: "updated",
      header: t("integration_source_column_updated"),
      width: proportional(1),
      sortable: true,
      renderCell: (row) => <SourceUpdated summary={row.summary} />
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (row) => {
        const [single] = row.source.items;
        return row.source.kind === "wrapper" ? (
          <WrapperActions
            wrapperId={row.source.id}
            wrapperName={row.name}
            itemCount={row.source.items.length}
            {...wrapperPermissions(row.source.items)}
          />
        ) : single ? (
          <IntegrationActions item={single} />
        ) : null;
      }
    }
  ];

  return (
    <div className="flex flex-col gap-3">
      <SignInStoppedBanner
        rows={signInStopped}
        filter={filter}
        onShowThem={() => setFilter("attention")}
      />
      {rows.length > 1 ? (
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <SegmentedControl
            label={t("integration_filter_label")}
            value={filter}
            onChange={(value) => setFilter(value as SourceFilter)}
            size="sm"
          >
            {SOURCE_FILTERS.filter(
              (option) => option === "all" || option === filter || counts[option] > 0
            ).map((option) => (
              <SegmentedControlItem
                key={option}
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
            resultCount={visible.length}
          />
        </div>
      ) : null}
      <SpaceTableFrame>
        <Table
          data={sortedData}
          columns={columns}
          idKey="id"
          aria-labelledby={labelledBy}
          plugins={{ sort: sortPlugin }}
          emptyState={<EmptyState title={t("no_results_found")} isCompact framed={false} />}
        />
      </SpaceTableFrame>
    </div>
  );
}
