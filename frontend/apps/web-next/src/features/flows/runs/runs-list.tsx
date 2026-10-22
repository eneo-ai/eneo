"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Selector } from "@astryxdesign/core/Selector";
import {
  proportional,
  useTableSortable,
  type TableColumn,
  type TableSortState
} from "@astryxdesign/core/Table";
import { FLOW_RUN_STATUS_FILTER_ORDER } from "@eneo/eneo-js/flows/run-status-capabilities";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { History, Search } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import { TextInput } from "@/components/astryx/text-input";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { useDebouncedValue } from "../editor/use-debounced-value";
import { formatCount, formatSeconds } from "./run-format";
import { starterName } from "./run-starter";
import {
  createPollClock,
  listNeedsPolling,
  listSignature,
  runDurationMs,
  runStatusView,
  statusChanges
} from "./run-status";
import {
  RUNS_MAX_PAGES,
  RUNS_PAGE_SIZE,
  runsListQueryOptions,
  type RunsSort,
  type RunStatus as RunStatusValue,
  type RunSummary
} from "./runs-api";

type Row = RunSummary & Record<string, unknown>;

/** The status filter's "every status" choice; no run status has this name. */
const ANY_STATUS = "any";
/** Newest start first, as the list opens. */
const DEFAULT_SORT: RunsSort = { key: "started_at", order: "desc" };
/** How long a search waits for the typing to stop before it asks again. */
const SEARCH_DELAY_MS = 300;

/** Where a run's own page is. */
export function runHref(spaceRouteId: string, flowId: string, runId: string): string {
  return `/spaces/${spaceRouteId}/flows/${flowId}/runs/${runId}`;
}

export function RunStatus({ status, purpose }: Pick<RunSummary, "status" | "purpose">) {
  const t = useTranslations();
  const view = runStatusView(status);
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <StatusLabel status={view.tone} label={t(view.labelKey)} isPulsing={view.isPulsing} />
      {purpose === "test" ? (
        <span className="text-ax-text-secondary border-ax-border rounded-ax-inner border px-1.5 text-xs">
          {t("flow_runs_purpose_test")}
        </span>
      ) : null}
    </span>
  );
}

/**
 * The run's name as the link to its page, with its start time under it; a
 * run started without a name is named by its start time.
 */
function RunLink({ run, href }: { run: RunSummary; href: string }) {
  const t = useTranslations();
  const startedAt = run.started_at ?? run.created_at;
  const time = useClientTimeText(startedAt, "date_time");
  const label = run.run_label?.trim();
  const linkClass =
    "text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 items-center font-medium underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2";
  if (label) {
    return (
      <span className="flex min-w-0 flex-col items-start">
        <Link href={href} className={`${linkClass} break-words`}>
          {label}
        </Link>
        <span className="text-ax-text-secondary text-xs">
          <ClientTime value={startedAt} format="date_time" />
        </span>
      </span>
    );
  }
  return (
    <Link
      href={href}
      aria-label={time ? t("flow_runs_open", { time }) : undefined}
      className={linkClass}
    >
      <ClientTime value={startedAt} format="date_time" />
    </Link>
  );
}

const SORT_KEYS: readonly RunsSort["key"][] = ["started_at", "status", "duration"];

function isSortKey(value: string): value is RunsSort["key"] {
  return (SORT_KEYS as readonly string[]).includes(value);
}

/**
 * A flow's runs, newest first: name, status, when each started, who started
 * it, how long it took and which version ran. The list endpoint searches
 * (name and starter), sorts (start, status, duration), narrows to one status
 * or to the caller's own runs, and counts the runs per status for the status
 * filter. The list keeps itself current while a run in it is queued, running
 * or waiting for review, on the cadence the run API asks for, and stops once
 * all of them have ended. A run that moves on is announced.
 */
export function FlowRunsList({
  flowId,
  spaceRouteId,
  headingLevel = 2
}: {
  flowId: string;
  spaceRouteId: string;
  headingLevel?: 2 | 3;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const headingId = useId();
  const [mine, setMine] = useState(false);
  const [status, setStatus] = useState<RunStatusValue | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [sort, setSort] = useState<RunsSort>(DEFAULT_SORT);
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [clock] = useState(() => createPollClock());
  const seen = useRef(new Map<string, string>());

  const runs = useInfiniteQuery({
    ...runsListQueryOptions(flowId, { mine, status, search, sort }),
    // A new search or order keeps the rows and counts on screen until it answers.
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const items = query.state.data?.pages.flatMap((page) => page.items) ?? [];
      return clock(listSignature(items), listNeedsPolling(items));
    },
    refetchIntervalInBackground: false
  });

  const items = useMemo(() => runs.data?.pages.flatMap((page) => page.items) ?? [], [runs.data]);

  // Announces each run that moved on since the last answer; comparing with
  // what was seen makes a repeated pass over the same answer a no-op.
  useEffect(() => {
    for (const run of statusChanges(seen.current, items)) {
      announce(t("flow_runs_status_changed", { status: t(runStatusView(run.status).labelKey) }));
    }
    seen.current = new Map(items.map((run) => [run.id, run.status]));
  }, [items, announce, t]);

  const sortState: TableSortState<RunsSort["key"]> = [
    { sortKey: sort.key, direction: sort.order === "asc" ? "ascending" : "descending" }
  ];
  const sortPlugin = useTableSortable<Row, RunsSort["key"]>({
    sort: sortState,
    onSortChange: (next) => {
      const first = next[0];
      if (!first || !isSortKey(first.sortKey)) return;
      setSort({ key: first.sortKey, order: first.direction === "ascending" ? "asc" : "desc" });
    },
    allowUnsortedState: false
  });
  const counts = runs.data?.pages[0]?.status_counts;
  const countText = (count: number | undefined) =>
    count === undefined ? "" : ` (${formatCount(count, locale)})`;
  const total = counts ? Object.values(counts).reduce((sum, count) => sum + count, 0) : undefined;

  const columns: TableColumn<Row>[] = [
    {
      key: "started_at",
      header: t("flow_run_journey_column_run"),
      width: proportional(3),
      sortable: true,
      renderCell: (run) => <RunLink run={run} href={runHref(spaceRouteId, flowId, run.id)} />
    },
    {
      key: "status",
      header: t("flow_runs_column_status"),
      width: proportional(3),
      sortable: true,
      renderCell: (run) => <RunStatus status={run.status} purpose={run.purpose} />
    },
    {
      key: "principal",
      header: t("flow_runs_column_started_by"),
      width: proportional(2),
      renderCell: (run) => starterName(run, t)
    },
    {
      key: "duration",
      header: t("flow_runs_column_duration"),
      width: proportional(2),
      sortable: true,
      renderCell: (run) => {
        const ms = runDurationMs(run);
        return ms === null ? "–" : formatSeconds(ms / 1000, t);
      }
    },
    {
      key: "version",
      header: t("flow_runs_column_version"),
      width: proportional(1),
      renderCell: (run) => t("flow_runs_version", { version: run.flow_version })
    }
  ];

  const Heading = `h${headingLevel}` as const;
  const shown = items.length;
  const capped = !runs.hasNextPage && runs.data?.pages.at(-1)?.has_more === true;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <Heading id={headingId} className="text-ax-text text-lg font-semibold">
        {t("flow_runs_heading")}
      </Heading>
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <TextInput
          label={t("flow_run_journey_search")}
          description={t("flow_run_journey_search_hint")}
          size="sm"
          width={280}
          startIcon={Search}
          value={searchInput}
          onChange={setSearchInput}
        />
        <Selector
          label={t("flow_run_extras_status_filter")}
          size="sm"
          width={240}
          value={status ?? ANY_STATUS}
          onChange={(value) => setStatus(value === ANY_STATUS ? null : (value as RunStatusValue))}
          options={[
            { value: ANY_STATUS, label: `${t("flow_run_extras_status_any")}${countText(total)}` },
            ...FLOW_RUN_STATUS_FILTER_ORDER.map((value) => ({
              value,
              label: `${t(runStatusView(value).labelKey)}${countText(counts?.[value])}`
            }))
          ]}
        />
        <CheckboxInput label={t("flow_runs_only_mine")} value={mine} onChange={setMine} />
      </div>
      {runs.isPending ? (
        <LoadingState rows={3} label={t("flow_runs_loading")} />
      ) : runs.isError ? (
        <ListError
          error={runs.error}
          title={t("flow_runs_list_failed")}
          onRetry={() => void runs.refetch()}
          isRetrying={runs.isFetching}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<History />}
          hue="purple"
          headingLevel={headingLevel === 2 ? 3 : 4}
          isCompact
          title={
            search
              ? t("flow_run_journey_search_empty_title", { search })
              : status
                ? t("flow_run_extras_status_empty_title", {
                    status: t(runStatusView(status).labelKey)
                  })
                : mine
                  ? t("flow_runs_empty_mine_title")
                  : t("flow_runs_empty_title")
          }
          description={
            search
              ? t("flow_run_journey_search_empty")
              : status
                ? t("flow_run_extras_status_empty")
                : t("flow_runs_empty_description")
          }
        />
      ) : (
        <>
          <Table<Row>
            data={items as Row[]}
            columns={columns}
            idKey="id"
            aria-labelledby={headingId}
            plugins={{ sort: sortPlugin }}
          />
          {runs.hasNextPage ? (
            <div className="flex justify-center">
              <Button
                label={t("flow_runs_show_more")}
                isLoading={runs.isFetchingNextPage}
                isInterruptible
                onClick={() => {
                  if (!runs.isFetchingNextPage) void runs.fetchNextPage();
                }}
              />
            </div>
          ) : null}
          {capped ? (
            <p className="text-ax-text-secondary text-sm">
              {t("flow_runs_capped", {
                count: new Intl.NumberFormat(locale).format(RUNS_MAX_PAGES * RUNS_PAGE_SIZE)
              })}
            </p>
          ) : (
            <p className="sr-only">{t("flow_runs_shown", { count: shown })}</p>
          )}
        </>
      )}
    </section>
  );
}
