"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { proportional, pixel, type TableColumn } from "@astryxdesign/core/Table";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState, type ReactNode } from "react";
import { Table } from "@/components/astryx/table";
import { EmptyState } from "@/components/composites/empty-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import {
  knowledgeOverviewQueryOptions,
  type KnowledgeOverview
} from "@/features/knowledge/integrations/queries";
import { isCredentialsError } from "@/features/knowledge/integrations/source-problems";
import { SourceStateLabel, SourceUpdated } from "@/features/knowledge/integrations/source-status";
import {
  countSourceFilters,
  groupSourcesBySpace,
  matchesSourceFilter,
  SOURCE_FILTERS,
  sourceContentsLabel,
  sourceHref,
  summarizeSource,
  waitingLabel,
  type IntegrationSource,
  type SourceFilter,
  type SourceSummary
} from "@/features/knowledge/integrations/sources";
import { VendorIcon } from "@/features/knowledge/integrations/vendor";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { spaceRouteId } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";

type OverviewSpace = KnowledgeOverview["items"][number]["space"];

type OverviewRow = {
  id: string;
  name: string;
  space: OverviewSpace;
  source: IntegrationSource;
  summary: SourceSummary;
};

function needsAttention(row: OverviewRow): boolean {
  return row.summary.failedItems.length > 0;
}

/** Whatever needs someone comes first; the rest by space, then source, in `compare`'s order. */
function rowOrder(compare: Intl.Collator["compare"]) {
  return (a: OverviewRow, b: OverviewRow): number =>
    Number(needsAttention(b)) - Number(needsAttention(a)) ||
    compare(a.space.name, b.space.name) ||
    compare(a.name, b.name);
}

function matchesQuery(row: OverviewRow, needle: string): boolean {
  if (needle === "") return true;
  return [row.name, row.space.name, ...row.source.items.map((item) => item.name)].some((text) =>
    text.toLocaleLowerCase().includes(needle)
  );
}

function SourceCell({ row }: { row: OverviewRow }) {
  const t = useTranslations();
  // The overview lists shared and organisation spaces only, never personal ones.
  const routeId = spaceRouteId({ ...row.space, personal: false });
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center">
        <VendorIcon type={row.source.integrationType} />
      </span>
      <span className="flex min-w-0 flex-col">
        {/* The admin permission alone opens no shared space: link only where its page would. */}
        {row.space.can_open ? (
          <Link
            href={sourceHref(routeId, row.source)}
            className="text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 w-fit items-center font-semibold break-words hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
          >
            {row.name}
          </Link>
        ) : (
          <span className="font-semibold break-words">{row.name}</span>
        )}
        <span className="text-ax-text-secondary text-xs">
          {sourceContentsLabel(row.source.items, t)}
        </span>
      </span>
    </span>
  );
}

/** Why the source needs attention, or which of its folders still wait for a first sync. */
function StatusCell({ summary }: { summary: SourceSummary }) {
  const t = useTranslations();
  const failure = summary.failedItems[0]?.metadata?.last_sync_error?.trim();
  const note = failure
    ? isCredentialsError(failure)
      ? t("integration_problem_credentials_title")
      : failure
    : waitingLabel(summary, t);
  return (
    <span className="flex min-w-0 flex-col items-start gap-1">
      <SourceStateLabel state={summary.state} />
      {note ? <span className="text-ax-text-secondary text-xs break-words">{note}</span> : null}
    </span>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: ReactNode }) {
  return (
    <div className="border-ax-border bg-ax-card rounded-ax-container flex flex-col gap-1 border px-4 py-3">
      <dt className="text-ax-text-secondary text-xs">{label}</dt>
      <dd className="flex flex-wrap items-baseline gap-x-1.5 text-xl font-semibold tabular-nums">
        {value}
        {/* A real space, so the note is not read run together with the number. */}
        {note ? " " : null}
        {note}
      </dd>
    </div>
  );
}

function OverviewContent({
  overview,
  labelledBy
}: {
  overview: KnowledgeOverview;
  labelledBy: string;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const collator = useCollator();
  const [filter, setFilter] = useState<SourceFilter>("all");
  const [query, setQuery] = useState("");

  const rows: OverviewRow[] = groupSourcesBySpace(overview.items, collator.compare).map(
    ({ space, source }) => ({
      id: `${space.id}:${source.kind}:${source.id}`,
      name: source.name,
      space,
      source,
      summary: summarizeSource(source.items, {})
    })
  );
  const counts = countSourceFilters(rows.map((row) => row.summary));
  const attentionSpaces = new Set(rows.filter(needsAttention).map((row) => row.space.id)).size;
  const documentTotal = rows.reduce((sum, row) => sum + row.summary.documentCount, 0);
  const needle = query.trim().toLocaleLowerCase();
  const visible = rows
    .filter((row) => matchesSourceFilter(row.summary, filter) && matchesQuery(row, needle))
    .sort(rowOrder(collator.compare));

  const columns: TableColumn<OverviewRow>[] = [
    {
      key: "name",
      header: t("integration_source_column_source"),
      width: proportional(3),
      renderCell: (row) => <SourceCell row={row} />
    },
    {
      key: "space",
      header: t("admin_sources_column_space"),
      width: proportional(2),
      renderCell: (row) => (
        <span className="break-words">
          {row.space.name}
          {row.space.organization ? (
            <span className="text-ax-text-secondary text-xs"> ({t("organization")})</span>
          ) : null}
        </span>
      )
    },
    {
      key: "documents",
      header: t("documents"),
      width: pixel(120),
      align: "end",
      renderCell: (row) => (
        <span className="tabular-nums">{format.number(row.summary.documentCount)}</span>
      )
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(2),
      renderCell: (row) => <StatusCell summary={row.summary} />
    },
    {
      key: "updated",
      header: t("integration_source_last_up_to_date"),
      width: proportional(2),
      renderCell: (row) => <SourceUpdated summary={row.summary} />
    }
  ];

  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t("admin_sources_stat_sources")} value={format.number(rows.length)} />
        <Stat
          label={t("admin_sources_stat_attention")}
          value={format.number(counts.attention)}
          note={
            attentionSpaces > 0 ? (
              <span className="text-ax-text-secondary text-xs font-normal">
                {attentionSpaces === 1
                  ? t("admin_sources_in_spaces_one")
                  : t("admin_sources_in_spaces_other", { count: attentionSpaces })}
              </span>
            ) : null
          }
        />
        <Stat label={t("admin_sources_stat_documents")} value={format.number(documentTotal)} />
        <Stat
          label={t("admin_sources_stat_personal")}
          value={format.number(overview.personal.items)}
          note={
            overview.personal.failing > 0 ? (
              <span className="text-ax-error text-xs font-normal">
                {t("admin_sources_personal_failing", { count: overview.personal.failing })}
              </span>
            ) : null
          }
        />
      </dl>

      {rows.length === 0 ? (
        <p className="text-ax-text-secondary text-sm">{t("admin_sources_none")}</p>
      ) : (
        <>
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
            <ResourceFilterInput
              value={query}
              onChange={setQuery}
              label={t("admin_sources_search")}
              placeholder={t("admin_sources_search")}
              resultCount={visible.length}
              className="sm:w-72"
            />
          </div>
          <SpaceTableFrame>
            <Table
              data={visible}
              columns={columns}
              idKey="id"
              aria-labelledby={labelledBy}
              emptyState={<EmptyState title={t("no_results_found")} isCompact framed={false} />}
            />
          </SpaceTableFrame>
        </>
      )}
    </div>
  );
}

/**
 * Every source imported into shared spaces and the organisation space, so an
 * admin sees what has stopped updating: totals, a status filter, a search on
 * source, folder or space name, and a table with what needs attention first.
 * Personal spaces are only counted; they can hold a person's own OneDrive.
 */
export function SourcesOverview() {
  const t = useTranslations();
  const headingId = useId();
  const query = useQuery(knowledgeOverviewQueryOptions(browserApi));

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="font-semibold">
          {t("admin_sources_heading")}
        </h2>
        <p className="text-ax-text-secondary text-sm">{t("admin_sources_row_description")}</p>
      </div>
      <QueryStateBoundary query={query} rows={4}>
        {(overview) => <OverviewContent overview={overview} labelledBy={headingId} />}
      </QueryStateBoundary>
    </section>
  );
}
