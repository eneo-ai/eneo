import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Selector } from "@astryxdesign/core/Selector";
import {
  pixel,
  proportional,
  useTableSortable,
  type TableColumn,
  type TableSortState
} from "@astryxdesign/core/Table";
import { FLOW_RUN_STATUS_FILTER_ORDER } from "@eneo/eneo-js/flows/run-status-capabilities";
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient
} from "@tanstack/react-query";
import { History, Search } from "lucide-react";
import Link from "@/lib/link";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Collapsible } from "@/components/astryx/collapsible";
import { Table } from "@/components/astryx/table";
import { TextInput } from "@/components/astryx/text-input";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import {
  blockingError,
  ListError,
  LoadMore,
  RefreshError
} from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { useAppContext } from "@/components/providers/app-context";
import { pollEvery } from "@/lib/api/query";
import { toastApiError } from "@/lib/api/toast";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { toast } from "@/lib/toast";
import { useDebouncedValue } from "../editor/use-debounced-value";
import { formatCount, formatSeconds } from "./run-format";
import { CancelRunButton, runActions, type RunActionNotice } from "./run-actions";
import { refusalText } from "./run-messages";
import { runHref } from "./run-routes";
import { starterName } from "./run-starter";
import { RunUsage, RunUsageBrief } from "./run-usage";
import { useStartedRuns, withStartedRuns } from "./runs-optimistic";
import {
  canRedispatch,
  createPollClock,
  isAwaitingReview,
  listNeedsPolling,
  listSignature,
  runDurationMs,
  runElapsedMs,
  runStatusView,
  statusChanges
} from "./run-status";
import {
  redispatchRun,
  runKeys,
  RUNS_MAX_PAGES,
  RUNS_PAGE_SIZE,
  runsListQueryOptions,
  type RunsFilter,
  type RunsSort,
  type RunStatus as RunStatusValue,
  type RunSummary,
  type RunListItem
} from "./runs-api";

type Row = RunListItem & Record<string, unknown>;

/** The status filter's "every status" choice; no run status has this name. */
const ANY_STATUS = "any";
/** Newest start first, as the list opens. */
const DEFAULT_SORT: RunsSort = { key: "started_at", order: "desc" };
/** How long a search waits for the typing to stop before it asks again. */
const SEARCH_DELAY_MS = 300;
/** The room the table's six columns need; with less, the rows stack as on a phone. */
export const RUNS_TABLE_WIDTH = 936;
/** Runs shown at a glance: filters above them would take more room than they do. */
const FEW_RUNS = 3;

// Where a run's own page is; kept here for the screens that link to runs.
export { runHref };

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
function RunLink({ id, run, href }: { id: string; run: RunSummary; href: string }) {
  const t = useTranslations();
  const startedAt = run.started_at ?? run.created_at;
  const time = useClientTimeText(startedAt, "date_time");
  const label = run.run_label?.trim();
  const linkClass =
    "text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 max-w-full items-center font-medium pointer-coarse:min-h-11 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2";
  if (label) {
    return (
      <span className="flex min-w-0 flex-col items-start">
        <Link id={id} href={href} className={`${linkClass} [overflow-wrap:anywhere]`}>
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
      id={id}
      href={href}
      aria-label={time ? t("flow_runs_open", { time }) : undefined}
      className={linkClass}
    >
      <ClientTime value={startedAt} format="date_time" />
    </Link>
  );
}

/**
 * "Försök starta nu" for a queued run whose dispatch is due or gave up (the
 * same rule as on the run's page); the list is read again after it.
 */
function RedispatchButton({ flowId, run }: { flowId: string; run: RunSummary }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const redispatch = useMutation({
    mutationFn: () => redispatchRun(flowId, run),
    onSuccess: (answer) => {
      if (answer.redispatched_count > 0) toast.success(t("flow_runs_redispatch_done"));
      else toast.info(t("flow_runs_redispatch_noop"));
      void queryClient.invalidateQueries({ queryKey: runKeys.list(flowId) });
    },
    onError: (error) =>
      toastApiError(error, t, {
        title: t("flow_runs_redispatch_failed"),
        message: refusalText(error, t)
      })
  });
  return (
    <Button
      label={t("flow_runs_redispatch")}
      size="sm"
      isLoading={redispatch.isPending}
      isInterruptible
      onClick={() => {
        if (!redispatch.isPending) redispatch.mutate();
      }}
    />
  );
}

/**
 * What came of a row's cancel, as a toast (errors stay until closed, with
 * the failure's support references).
 */
function toastNotice(notice: RunActionNotice, t: (key: string) => string) {
  if (notice.status === "error") {
    toastApiError(notice.error, t, { title: notice.title, message: notice.description });
    return;
  }
  const options = notice.description ? { description: notice.description } : undefined;
  switch (notice.status) {
    case "warning":
      toast.warning(notice.title, options);
      return;
    case "info":
      toast.info(notice.title, options);
      return;
    case "success":
      toast.success(notice.title, options);
  }
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
 * filter (a run still going shows how long it has gone on so far). The list
 * keeps itself current while a run in it is queued, running
 * or waiting for review, on the cadence the run API asks for, and stops once
 * all of them have ended. A run that moves on is announced. A queued run
 * whose start is due or gave up can be sent again from its row and a run
 * under way cancelled, by the run page's rules (`run-actions.tsx`); a failed
 * run is run again from its page, which knows its steps. A run this tab
 * just started shows at once (`runs-optimistic.ts`). A flow with no runs that is not published yet
 * says to publish it first.
 */
export function FlowRunsList({
  flowId,
  spaceRouteId,
  publishedVersion,
  headingLevel = 2
}: {
  flowId: string;
  spaceRouteId: string;
  /** The flow's published version, for the empty list's words and the run page's rules. */
  publishedVersion: number | null;
  headingLevel?: 2 | 3;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const { can, user } = useAppContext();
  const report = (notice: RunActionNotice) => toastNotice(notice, t);
  // A cancelled run's button goes: focus moves to the run's link in its row,
  // or to the heading when the run left the list (a status filter).
  const rescue = useFocusRescue();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const headingId = useId();
  const linkId = (runId: string) => `${headingId}-run-${runId}`;
  // A phone lists the runs as rows: six columns do not fit, and what it needs is the run, how it went, and the buttons.
  const phone = usePhoneScreen();
  // So does a panel beside the chat: what counts is the room here, not the window's.
  const sectionRef = useRef<HTMLElement>(null);
  // The observer answers after the first paint; measured before it, the table never flashes.
  const [firstNarrow, setFirstNarrow] = useState<boolean | null>(null);
  useLayoutEffect(() => {
    const width = sectionRef.current?.getBoundingClientRect().width ?? 0;
    if (width > 0) setFirstNarrow(width < RUNS_TABLE_WIDTH);
  }, []);
  const narrow =
    useElementWidth(sectionRef, (width) => width < RUNS_TABLE_WIDTH) ?? firstNarrow ?? false;
  const stacked = phone || narrow;
  const person = { canRun: can("flows_run"), userId: user.id, publishedVersion };
  const [mine, setMine] = useState(false);
  const [status, setStatus] = useState<RunStatusValue | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [sort, setSort] = useState<RunsSort>(DEFAULT_SORT);
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [clock] = useState(() => createPollClock());
  const seen = useRef(new Map<string, string>());

  const filter: RunsFilter = { mine, status, search, sort };
  const started = useStartedRuns(flowId);
  const runs = useInfiniteQuery({
    ...runsListQueryOptions(flowId, filter),
    // A new search or order keeps the rows and counts on screen until it answers.
    placeholderData: keepPreviousData,
    refetchInterval: pollEvery((data) => {
      const items = data?.pages.flatMap((page) => page.items) ?? [];
      return clock(listSignature(items), listNeedsPolling(items));
    }),
    refetchIntervalInBackground: false
  });

  const listed = useMemo(() => runs.data?.pages.flatMap((page) => page.items) ?? [], [runs.data]);
  const shown = withStartedRuns(
    listed,
    runs.data?.pages[0]?.status_counts ?? undefined,
    started,
    filter,
    runs.dataUpdatedAt
  );
  const items = shown.items;
  // A list with next to nothing to filter has no use for the three controls: they would take more
  // room than the runs. A search that finds little keeps them, and so does the list on its way back
  // from one (`isPlaceholderData`), or the field being typed in would go.
  const showFilters =
    items.length > FEW_RUNS || search !== "" || status !== null || mine || runs.isPlaceholderData;

  // Announces each run that moved on since the last answer; comparing with
  // what was seen makes a repeated pass over the same answer a no-op.
  useEffect(() => {
    for (const run of statusChanges(seen.current, listed)) {
      announce(t("flow_runs_status_changed", { status: t(runStatusView(run.status).labelKey) }));
    }
    seen.current = new Map(listed.map((run) => [run.id, run.status]));
  }, [listed, announce, t]);

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
  const counts = shown.counts;
  const countText = (count: number | undefined) =>
    count === undefined ? "" : ` (${formatCount(count, locale)})`;
  const total = counts ? Object.values(counts).reduce((sum, count) => sum + count, 0) : undefined;

  /**
   * A run's state, with the actions its state allows: review it (on its page), send it again,
   * cancel it. Running a failed run again is offered on its page, which knows its steps.
   */
  const statusCell = (run: Row) => {
    const redispatch = canRedispatch(run, runs.dataUpdatedAt);
    const offers = runActions(run, person, null);
    const review = isAwaitingReview(run.status);
    return (
      <span className="flex flex-col items-start gap-1">
        <RunStatus status={run.status} purpose={run.purpose} />
        {review || redispatch || offers.cancel ? (
          <span className="flex flex-wrap gap-1">
            {review ? (
              <Button
                label={t("flow_runs_review_open")}
                variant="primary"
                size="sm"
                href={runHref(spaceRouteId, flowId, run.id)}
              />
            ) : null}
            {redispatch ? <RedispatchButton flowId={flowId} run={run} /> : null}
            {offers.cancel ? (
              <CancelRunButton
                flowId={flowId}
                runId={run.id}
                report={report}
                onCancelled={() =>
                  rescue(() => document.getElementById(linkId(run.id)) ?? headingRef.current)
                }
                size="sm"
                variant={review ? "ghost" : "destructive"}
              />
            ) : null}
          </span>
        ) : null}
      </span>
    );
  };
  /** How long a run took, took so far, or has waited for its review; null when it has not started. */
  const durationOrNull = (run: Row) => {
    const ms = runDurationMs(run);
    if (ms !== null) return formatSeconds(ms / 1000, t);
    if (isAwaitingReview(run.status)) {
      // The person's wait, not the run working: from the run's last change, which for a paused
      // run is when it paused, as of the list's last read.
      const waited = runs.dataUpdatedAt - Date.parse(run.updated_at);
      return Number.isFinite(waited) && waited >= 0
        ? t("flow_runs_waited", { time: formatSeconds(waited / 1000, t) })
        : null;
    }
    // A run still going: how long so far, as of the list's last read.
    const elapsed = runElapsedMs(run, runs.dataUpdatedAt);
    return elapsed === null
      ? null
      : t("flow_run_more_elapsed", { time: formatSeconds(elapsed / 1000, t) });
  };
  /** The table cell: a dash under the "Tid" header says there is no time yet. */
  const durationText = (run: Row) => durationOrNull(run) ?? "–";

  const columns: TableColumn<Row>[] = [
    {
      key: "started_at",
      header: t("flow_runs_column_started"),
      width: proportional(3),
      sortable: true,
      renderCell: (run) => (
        <RunLink id={linkId(run.id)} run={run} href={runHref(spaceRouteId, flowId, run.id)} />
      )
    },
    {
      key: "status",
      header: t("flow_runs_column_status"),
      width: proportional(3),
      sortable: true,
      renderCell: statusCell
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
      renderCell: durationText
    },
    {
      key: "usage",
      header: t("flow_runs_usage_heading"),
      // In pixels, as is the version: a share's floor scales with the other shares, so these two
      // would set the whole table's width. `RUNS_TABLE_WIDTH` is the sum of the floors.
      width: pixel(240),
      renderCell: (run) => <RunUsage run={run} compact />
    },
    {
      key: "version",
      header: t("flow_runs_column_version"),
      width: pixel(96),
      renderCell: (run) => t("flow_runs_version", { version: run.flow_version })
    }
  ];

  const Heading = `h${headingLevel}` as const;
  const shownCount = items.length;
  const capped = !runs.hasNextPage && runs.data?.pages.at(-1)?.has_more === true;

  return (
    <section
      ref={sectionRef}
      aria-labelledby={headingId}
      // The sort buttons are 24 px tall with a mouse as well (WCAG 2.5.8); touch gets 44 from globals.css 9b.
      className="flex flex-col gap-3 [&_.astryx-table-header-cell_button]:min-h-6"
    >
      <Heading
        id={headingId}
        ref={headingRef}
        tabIndex={-1}
        className="text-ax-text focus-visible:outline-ring text-lg font-semibold focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {t("flow_runs_heading")}
      </Heading>
      {showFilters ? (
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <TextInput
            label={t("flow_run_journey_search")}
            description={phone ? undefined : t("flow_run_journey_search_hint")}
            size="sm"
            width={phone ? "100%" : 280}
            startIcon={Search}
            value={searchInput}
            onChange={setSearchInput}
          />
          <Selector
            label={t("flow_run_extras_status_filter")}
            size="sm"
            width={phone ? "100%" : 240}
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
      ) : null}
      {/* A failed poll keeps the rows read so far; a failed older page is LoadMore's. */}
      <RefreshError queries={[runs]} />
      {blockingError(runs) ? (
        <ListError
          error={runs.error}
          title={t("flow_runs_list_failed")}
          onRetry={() => void runs.refetch()}
          isRetrying={runs.isFetching}
        />
      ) : runs.isPending ? (
        <LoadingState rows={3} label={t("flow_runs_loading")} />
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
                : publishedVersion === null
                  ? // A phone cannot publish: it says where that is done.
                    t(
                      phone
                        ? "flow_runs_empty_description_unpublished_phone"
                        : "flow_runs_empty_description_unpublished"
                    )
                  : t("flow_runs_empty_description")
          }
        />
      ) : (
        <>
          {stacked ? (
            <ul aria-labelledby={headingId} className="m-0 flex list-none flex-col p-0">
              {(items as Row[]).map((run) => (
                <li
                  key={run.id}
                  className="border-ax-border flex flex-col items-start gap-1.5 border-b py-3 first:pt-0 last:border-b-0"
                >
                  <RunLink
                    id={linkId(run.id)}
                    run={run}
                    href={runHref(spaceRouteId, flowId, run.id)}
                  />
                  {statusCell(run)}
                  <span className="text-ax-text-secondary text-sm">
                    {/* No header names the time here, so a missing one is left out, not a bare dash. */}
                    {[
                      starterName(run, t),
                      durationOrNull(run),
                      phone ? null : t("flow_runs_version", { version: run.flow_version })
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                  {/* Beside the chat there is room for it; a phone reads it on the run's page. */}
                  {phone ? null : (
                    <span className="flex flex-wrap gap-x-3 text-sm">
                      <RunUsageBrief run={run} />
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <Table<Row>
              data={items as Row[]}
              columns={columns}
              idKey="id"
              aria-labelledby={headingId}
              plugins={{ sort: sortPlugin }}
            />
          )}
          {!stacked && items.some((run) => run.token_usage) ? (
            <Collapsible
              trigger={
                // As tall as a step's folds (32 px); a bare span is trimmed to the text's cap height.
                <span className="block py-1.5 text-sm">
                  {t("flow_runs_usage_tokens_explainer_title")}
                </span>
              }
              defaultIsOpen={false}
              chevronPosition="start"
            >
              <p className="text-ax-text-secondary m-0 max-w-prose pt-1 text-sm">
                {t("flow_runs_usage_tokens_explainer")}
              </p>
            </Collapsible>
          ) : null}
          <LoadMore query={runs} label={t("flow_runs_show_more")} />
          {capped ? (
            <p className="text-ax-text-secondary text-sm">
              {t("flow_runs_capped", {
                count: new Intl.NumberFormat(locale).format(RUNS_MAX_PAGES * RUNS_PAGE_SIZE)
              })}
            </p>
          ) : (
            <p className="sr-only">{t("flow_runs_shown", { count: shownCount })}</p>
          )}
        </>
      )}
    </section>
  );
}
