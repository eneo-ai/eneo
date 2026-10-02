"use client";

import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Pagination } from "@astryxdesign/core/Pagination";
import { Selector } from "@astryxdesign/core/Selector";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { TextInput } from "@/components/astryx/text-input";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowRight, RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { crawlRunState, crawlRunStateLabelKey } from "@/features/knowledge/crawl-run-state";
import {
  CrawlLoadError,
  CrawlRunCounts,
  CrawlRunStatusLabel
} from "@/features/knowledge/crawl-run-ui";
import { CrawlDetailsDialog } from "./crawl-details-dialog";
import {
  CRAWLER_PAGE_SIZE,
  crawlerOverviewQueryOptions,
  crawlerScheduleQueryOptions,
  type CrawlerItem,
  type CrawlerPeriod,
  type CrawlerStatusFilter,
  type CrawlerView,
  type ScheduleInterval,
  type ScheduleSort,
  type ScheduleStateFilter
} from "./crawler";
import { elapsedParts, intervalLabelKey } from "./schedule-format";
import { ScheduleTable } from "./schedule-table";
import { SchedulerHealth } from "./scheduler-health";

const REFRESH_MS = 10_000;

type Day = "today" | "yesterday";
const DAYS: Day[] = ["today", "yesterday"];
const DAY_OUTCOMES = [
  { count: "completed", status: "completed" },
  { count: "partial", status: "warnings" },
  { count: "failed", status: "unsuccessful" }
] as const;
const PERIODS: CrawlerPeriod[] = ["today", "yesterday", "last_24_hours"];
const SCHEDULE_INTERVALS: ("all" | ScheduleInterval)[] = [
  "all",
  "daily",
  "every_other_day",
  "weekly",
  "never"
];
const SCHEDULE_STATES: ("all" | ScheduleStateFilter)[] = ["all", "due", "waiting", "blocked"];
const ACTIVE_STATUSES: CrawlerStatusFilter[] = ["queued", "running", "finalizing", "stopping"];
const FINISHED_STATUSES: CrawlerStatusFilter[] = [
  "completed",
  "warnings",
  "unsuccessful",
  "cancelled",
  "issues"
];

const STATUS_LABEL_KEYS: Record<"issues" | "completed" | "warnings" | "unsuccessful", string> = {
  issues: "admin_crawler_issues",
  completed: "admin_crawler_completed_clean",
  warnings: "admin_crawler_with_warnings",
  unsuccessful: "admin_crawler_unsuccessful"
};

const PERIOD_KEYS: Record<CrawlerPeriod, string> = {
  today: "admin_crawler_today",
  yesterday: "admin_crawler_yesterday",
  last_24_hours: "admin_crawler_last_day"
};

const SCHEDULE_STATE_KEYS: Record<ScheduleStateFilter, string> = {
  due: "admin_crawler_state_due",
  waiting: "admin_crawler_state_waiting",
  blocked: "admin_crawler_state_blocked"
};

type Translate = (key: string, values?: Record<string, string | number>) => string;

type CrawlerRow = CrawlerItem & { id: string };

function statusLabel(t: Translate, status: "all" | CrawlerStatusFilter): string {
  if (status === "all") return t("admin_crawler_all_statuses");
  switch (status) {
    case "completed":
    case "warnings":
    case "unsuccessful":
    case "issues":
      return t(STATUS_LABEL_KEYS[status]);
    default:
      return t(crawlRunStateLabelKey(status));
  }
}

/** The filters of the overview and schedule lists; a change restarts paging. */
type Filters = {
  view: CrawlerView;
  period: CrawlerPeriod;
  status: "all" | CrawlerStatusFilter;
  search: string;
  interval: "all" | ScheduleInterval;
  scheduleState: "all" | ScheduleStateFilter;
  sort: ScheduleSort;
};

const DEFAULT_FILTERS: Filters = {
  view: "all",
  period: "today",
  status: "all",
  search: "",
  interval: "all",
  scheduleState: "all",
  sort: "next_due"
};

/** When the run started and how long it has run (or took); for a queued run, how long it has waited. */
function RunTimeCell({ item, asOf }: { item: CrawlerItem; asOf: string }) {
  const t = useTranslations();
  const startedAt = useClientTimeText(item.started_at, "date_time");
  const state = crawlRunState(item.run);
  if (state === "queued" && item.run.created_at) {
    return (
      <span className="text-xs">
        {t("admin_crawler_wait", {
          duration: t("admin_crawler_elapsed", elapsedParts(item.run.created_at, asOf))
        })}
      </span>
    );
  }
  if (!item.started_at) return "—";
  return (
    <span className="flex flex-col gap-1 text-xs">
      <span>{t("admin_crawler_started", { time: startedAt ?? "—" })}</span>
      <span className="text-ax-text-secondary">
        {t("admin_crawler_elapsed", elapsedParts(item.started_at, item.run.finished_at ?? asOf))}
      </span>
    </span>
  );
}

/**
 * The crawler overview for administrators: what is running and queued, what
 * ended today and yesterday, whether the scheduler is healthy, and the runs
 * (or scheduled websites) filtered by view, period, status and search. It
 * refreshes every ten seconds while the page is visible.
 */
export function CrawlerPage() {
  const t = useTranslations();
  const locale = useLocale();
  const baseId = useId();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const { view, period, status, search, interval, scheduleState, sort } = filters;
  const cursor = cursors.at(-1) ?? null;
  const isSchedule = view === "schedule";

  // The schedule view still needs the overview for the summary, the day
  // cards and the scheduler status, but not its rows.
  const overview = useQuery({
    ...crawlerOverviewQueryOptions(
      browserApi,
      isSchedule
        ? { view: "all", period, time_zone: timeZone, search: "", limit: 1, cursor: null }
        : {
            view,
            period,
            time_zone: timeZone,
            status: status === "all" ? undefined : status,
            search,
            limit: CRAWLER_PAGE_SIZE,
            cursor
          }
    ),
    placeholderData: keepPreviousData,
    refetchInterval: REFRESH_MS
  });
  const schedule = useQuery({
    ...crawlerScheduleQueryOptions(browserApi, {
      search,
      interval: interval === "all" ? undefined : interval,
      state: scheduleState === "all" ? undefined : scheduleState,
      sort,
      limit: CRAWLER_PAGE_SIZE,
      cursor
    }),
    enabled: isSchedule,
    placeholderData: keepPreviousData,
    refetchInterval: REFRESH_MS
  });

  const data = overview.data;
  const fetchedAt = useClientTimeText(data?.as_of, "date_time");
  const rows = isSchedule ? schedule : overview;
  const nextCursor = isSchedule ? schedule.data?.next_cursor : data?.next_cursor;
  const filtered =
    Boolean(search) || status !== "all" || interval !== "all" || scheduleState !== "all";
  const loading = overview.isFetching || (isSchedule && schedule.isFetching);

  function patch(next: Partial<Filters>) {
    setFilters((current) => ({ ...current, ...next }));
    setCursors([null]);
  }

  function changeView(next: CrawlerView) {
    patch({ view: next, status: "all" });
  }

  function showIssues() {
    setSearchInput("");
    patch({ view: "recent", status: "issues", period: "last_24_hours", search: "" });
  }

  function showDay(day: Day, outcome: CrawlerStatusFilter) {
    setSearchInput("");
    patch({ view: "recent", period: day, status: outcome, search: "" });
  }

  function clearFilters() {
    setSearchInput("");
    patch({ status: "all", interval: "all", scheduleState: "all", search: "" });
  }

  function openRun(runId: string) {
    setSelectedRunId(runId);
    setDetailsOpen(true);
  }

  const statuses: ("all" | CrawlerStatusFilter)[] = [
    "all",
    ...(view !== "recent" ? ACTIVE_STATUSES : []),
    ...(view !== "active" ? FINISHED_STATUSES : [])
  ];
  const dayValue =
    view === "recent" && (period === "today" || period === "yesterday")
      ? `${period}:${status}`
      : null;

  const views: { id: CrawlerView; label: string }[] = [
    { id: "all", label: t("admin_crawler_all_view") },
    { id: "active", label: t("admin_crawler_active") },
    { id: "recent", label: t("admin_crawler_completed_view") },
    { id: "schedule", label: t("admin_crawler_schedule") }
  ];
  const panelId = `${baseId}-panel`;
  const tabId = (id: CrawlerView) => `${baseId}-tab-${id}`;

  // Astryx Table keys rows by a string field; a run's id is nested.
  const items: CrawlerRow[] = (data?.items ?? []).map((item) => ({ ...item, id: item.run.id }));
  const columns: TableColumn<CrawlerRow>[] = [
    {
      key: "website",
      header: t("website"),
      width: proportional(3),
      renderCell: (item) => {
        const name = item.website_name || item.website_url;
        return (
          <span className="flex min-w-0 flex-col items-start gap-1">
            <Button variant="ghost" size="sm" label={name} onClick={() => openRun(item.run.id)}>
              <span className="break-all whitespace-normal">{name}</span>
            </Button>
            {item.website_name ? (
              <span className="text-ax-text-secondary text-xs break-all">{item.website_url}</span>
            ) : null}
          </span>
        );
      }
    },
    {
      key: "space",
      header: t("admin_crawler_space"),
      width: proportional(2),
      renderCell: (item) => item.space_name ?? "—"
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(2),
      renderCell: (item) => <CrawlRunStatusLabel run={item.run} />
    },
    {
      key: "result",
      header: t("admin_crawler_result"),
      width: pixel(260),
      renderCell: (item) => <CrawlRunCounts run={item.run} />
    },
    {
      key: "time",
      header: t("admin_crawler_time"),
      width: proportional(2),
      renderCell: (item) => (
        <RunTimeCell item={item} asOf={data?.as_of ?? item.run.created_at ?? ""} />
      )
    },
    {
      key: "last_indexed",
      header: t("admin_crawler_last_indexed"),
      width: proportional(2),
      renderCell: (item) =>
        item.last_indexed_at ? (
          <span className="text-xs">
            <ClientTime value={item.last_indexed_at} format="date_time" />
          </span>
        ) : (
          "—"
        )
    }
  ];

  const emptyTitle =
    search || status !== "all"
      ? t("admin_crawler_empty_filtered")
      : view === "active"
        ? t("admin_crawler_empty_active")
        : view === "all"
          ? t("admin_crawler_empty_all")
          : t("admin_crawler_empty_recent");

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        title={t("admin_crawler_title")}
        description={t("admin_crawler_description")}
        actions={
          <Button
            label={t("refresh")}
            icon={<RefreshCw aria-hidden="true" />}
            isLoading={loading}
            isInterruptible
            onClick={() => {
              if (loading) return;
              void overview.refetch();
              if (isSchedule) void schedule.refetch();
            }}
          />
        }
      />

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <p>
          {t("admin_crawler_ongoing")}
          <strong className="ms-2 tabular-nums">{data?.summary.ongoing ?? "—"}</strong>
        </p>
        <p>
          {t("admin_crawler_queued")}
          <strong className="ms-2 tabular-nums">{data?.summary.queued ?? "—"}</strong>
        </p>
        <div className="sm:ms-auto">
          <Button
            variant="ghost"
            size="sm"
            label={t("admin_crawler_show_issues")}
            endContent={<ArrowRight aria-hidden="true" />}
            onClick={showIssues}
          >
            {t("admin_crawler_issues")} · {t("admin_crawler_last_day")}{" "}
            <span className="tabular-nums">{data?.summary.issues ?? "—"}</span>
          </Button>
        </div>
      </div>

      {data ? <SchedulerHealth scheduler={data.scheduler} /> : null}

      <section className="flex flex-col gap-3" aria-label={t("admin_crawler_completed_view")}>
        <ToggleButtonGroup
          label={t("admin_crawler_completed_view")}
          value={dayValue}
          onChange={(value) => {
            if (typeof value !== "string") return;
            const [day, outcome] = value.split(":") as [Day, CrawlerStatusFilter];
            showDay(day, outcome);
          }}
        >
          <div className="grid gap-4 lg:grid-cols-2">
            {DAYS.map((day) => (
              <Card key={day} padding={3}>
                <div
                  role="group"
                  aria-labelledby={`${baseId}-${day}`}
                  className="flex flex-col gap-2"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 id={`${baseId}-${day}`} className="font-semibold">
                      {t(PERIOD_KEYS[day])}
                    </h2>
                    {data ? (
                      <span className="text-ax-text-secondary text-sm">
                        <ClientTime
                          value={`${data.calendar[day].date}T00:00:00Z`}
                          format="date_long"
                        />
                      </span>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {DAY_OUTCOMES.map((outcome) => (
                      <ToggleButton
                        key={outcome.status}
                        value={`${day}:${outcome.status}`}
                        label={t("admin_crawler_show_day_status", {
                          status: statusLabel(t, outcome.status),
                          day: t(PERIOD_KEYS[day])
                        })}
                        isDisabled={!data}
                      >
                        <span className="flex min-w-0 flex-col items-start gap-1 text-start">
                          <span className="text-xl font-semibold tabular-nums">
                            {data ? data.calendar[day][outcome.count].toLocaleString(locale) : "—"}
                          </span>
                          <span className="text-ax-text-secondary text-xs leading-5 whitespace-normal">
                            {statusLabel(t, outcome.status)}
                          </span>
                        </span>
                      </ToggleButton>
                    ))}
                  </div>
                  <div>
                    <ToggleButton
                      size="sm"
                      value={`${day}:cancelled`}
                      label={t("admin_crawler_show_day_status", {
                        status: statusLabel(t, "cancelled"),
                        day: t(PERIOD_KEYS[day])
                      })}
                      isDisabled={!data}
                    >
                      <span className="text-ax-text-secondary text-xs whitespace-normal">
                        {t("admin_crawler_cancelled_count", {
                          count: data ? data.calendar[day].cancelled.toLocaleString(locale) : "—"
                        })}
                      </span>
                    </ToggleButton>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </ToggleButtonGroup>
        <p className="text-ax-text-secondary max-w-3xl text-xs leading-5">
          {t("admin_crawler_calendar_help", { timeZone: data?.calendar.time_zone ?? timeZone })}
        </p>
      </section>

      <div className="flex flex-col gap-4">
        <TabList
          role="tablist"
          aria-label={t("admin_crawler_title")}
          value={view}
          onChange={(value) => changeView(value as CrawlerView)}
          hasDivider
        >
          {views.map((item) => (
            <Tab
              key={item.id}
              id={tabId(item.id)}
              value={item.id}
              label={item.label}
              panelId={panelId}
            />
          ))}
        </TabList>
        <div
          role="tabpanel"
          id={panelId}
          aria-labelledby={tabId(view)}
          className="flex flex-col gap-4"
        >
          {view === "all" ? (
            <p className="text-ax-text-secondary text-xs">{t("admin_crawler_all_help")}</p>
          ) : isSchedule ? (
            <p className="text-ax-text-secondary text-xs">{t("admin_crawler_schedule_help")}</p>
          ) : null}

          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              patch({ search: searchInput.trim() });
            }}
          >
            <TextInput
              label={t("admin_crawler_search")}
              placeholder={t("admin_crawler_search_hint")}
              value={searchInput}
              onChange={setSearchInput}
              width="18rem"
            />
            {view !== "active" && !isSchedule ? (
              <Selector
                label={t("admin_crawler_period")}
                options={PERIODS.map((option) => ({
                  value: option,
                  label: t(PERIOD_KEYS[option])
                }))}
                value={period}
                onChange={(value) => patch({ period: value as CrawlerPeriod })}
                width="11rem"
              />
            ) : null}
            {isSchedule ? (
              <>
                <Selector
                  label={t("admin_crawler_interval")}
                  options={SCHEDULE_INTERVALS.map((option) => ({
                    value: option,
                    label:
                      option === "all"
                        ? t("admin_crawler_all_scheduled")
                        : t(intervalLabelKey(option))
                  }))}
                  value={interval}
                  onChange={(value) => patch({ interval: value as "all" | ScheduleInterval })}
                  width="11rem"
                />
                <Selector
                  label={t("status")}
                  options={SCHEDULE_STATES.map((option) => ({
                    value: option,
                    label:
                      option === "all"
                        ? t("admin_crawler_all_states")
                        : t(SCHEDULE_STATE_KEYS[option])
                  }))}
                  value={scheduleState}
                  onChange={(value) =>
                    patch({ scheduleState: value as "all" | ScheduleStateFilter })
                  }
                  width="11rem"
                />
              </>
            ) : (
              <Selector
                label={t("status")}
                options={statuses.map((option) => ({
                  value: option,
                  label: statusLabel(t, option)
                }))}
                value={status}
                onChange={(value) => patch({ status: value as "all" | CrawlerStatusFilter })}
                width="14rem"
              />
            )}
            <Button type="submit" label={t("search")} />
            {searchInput || filtered ? (
              <Button
                variant="ghost"
                label={t("admin_crawler_clear_filters")}
                onClick={clearFilters}
              />
            ) : null}
          </form>

          {rows.isError ? (
            <CrawlLoadError
              message={data ? t("admin_crawler_refresh_error") : t("admin_crawler_error")}
              loading={rows.isFetching}
              onRetry={() => void rows.refetch()}
            />
          ) : null}

          {rows.isPending && !rows.isError ? (
            <LoadingState rows={3} />
          ) : isSchedule && schedule.data ? (
            <ScheduleTable
              items={schedule.data.items}
              asOf={schedule.data.as_of}
              sort={sort}
              filtered={filtered}
              onSort={(next) => patch({ sort: next })}
              onSelect={openRun}
            />
          ) : !isSchedule && data ? (
            data.items.length === 0 ? (
              <EmptyState title={emptyTitle} headingLevel={3} isCompact />
            ) : (
              <Table
                data={items}
                columns={columns}
                idKey="id"
                aria-labelledby={tabId(view)}
                className="min-w-[960px]"
              />
            )
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-ax-text-secondary text-xs">
              {isSchedule && schedule.data
                ? `${t("admin_crawler_scheduled_count", {
                    count: schedule.data.total_count.toLocaleString(locale)
                  })} · `
                : ""}
              {data ? t("admin_crawler_fetched", { time: fetchedAt ?? "—" }) : ""}
            </p>
            {cursors.length > 1 || nextCursor ? (
              <Pagination
                variant="none"
                size="sm"
                page={cursors.length}
                hasMore={Boolean(nextCursor)}
                isDisabled={rows.isFetching}
                onChange={(page) =>
                  setCursors((current) =>
                    page < current.length
                      ? current.slice(0, page)
                      : nextCursor
                        ? [...current, nextCursor]
                        : current
                  )
                }
                label={views.find((item) => item.id === view)?.label ?? t("admin_crawler_title")}
              />
            ) : null}
          </div>
        </div>
      </div>

      {selectedRunId ? (
        <CrawlDetailsDialog
          runId={selectedRunId}
          isOpen={detailsOpen}
          onOpenChange={setDetailsOpen}
          onSelect={setSelectedRunId}
          onChange={() => {
            void overview.refetch();
            if (isSchedule) void schedule.refetch();
          }}
        />
      ) : null}
    </div>
  );
}
