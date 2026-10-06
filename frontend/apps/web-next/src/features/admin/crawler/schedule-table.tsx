"use client";

import { Button } from "@astryxdesign/core/Button";
import {
  pixel,
  proportional,
  useTableSortable,
  type TableColumn,
  type TableSortState
} from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { useLocale, useTranslations } from "next-intl";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { CrawlRunStatusLabel } from "@/features/knowledge/crawl-run-ui";
import type { CrawlerScheduledWebsite, ScheduleSort } from "./crawler";
import { intervalLabelKey, relativeDue, SCHEDULE_SORT_DIRECTIONS } from "./schedule-format";

const SCHEDULE_STATE: Record<
  CrawlerScheduledWebsite["schedule_state"],
  { tone: StatusTone; labelKey: string }
> = {
  due: { tone: "accent", labelKey: "admin_crawler_state_due" },
  waiting: { tone: "neutral", labelKey: "admin_crawler_state_waiting" },
  blocked_active_run: { tone: "accent", labelKey: "admin_crawler_state_blocked_active" },
  blocked_backoff: { tone: "warning", labelKey: "admin_crawler_state_blocked_backoff" },
  disabled: { tone: "neutral", labelKey: "disabled" }
};

/** The website's name over its address; a button to its latest run when it has one. */
function WebsiteCell({
  item,
  onSelect
}: {
  item: CrawlerScheduledWebsite;
  onSelect: (runId: string) => void;
}) {
  const t = useTranslations();
  const name = item.website_name || item.website_url;
  const latestRunId = item.latest_run?.id;
  return (
    <span className="flex min-w-0 flex-col items-start gap-1">
      {latestRunId ? (
        <Button variant="ghost" size="sm" label={name} onClick={() => onSelect(latestRunId)}>
          <span className="break-all whitespace-normal">{name}</span>
        </Button>
      ) : (
        <>
          <span className="break-all">{name}</span>
          <span className="text-ax-text-secondary text-xs">{t("admin_crawler_no_run")}</span>
        </>
      )}
      {item.website_name ? (
        <span className="text-ax-text-secondary text-xs break-all">{item.website_url}</span>
      ) : null}
    </span>
  );
}

/** The schedule state as a status dot; a backoff says until when (after hydration). */
function ScheduleStateCell({ item }: { item: CrawlerScheduledWebsite }) {
  const t = useTranslations();
  const state = SCHEDULE_STATE[item.schedule_state];
  const until = useClientTimeText(item.blocked_until ?? item.next_retry_at, "date_time");
  const label =
    item.schedule_state === "blocked_backoff"
      ? t(state.labelKey, { time: until ?? "—" })
      : t(state.labelKey);
  return <StatusLabel status={state.tone} label={label} />;
}

/** Failures in a row and, after a backoff, when the next try is. */
function FailuresCell({ item }: { item: CrawlerScheduledWebsite }) {
  const t = useTranslations();
  const retryAt = useClientTimeText(item.next_retry_at, "date_time");
  return (
    <span className="flex flex-col items-start gap-0.5 text-xs tabular-nums">
      <span>{item.consecutive_failures}</span>
      {item.consecutive_failures > 0 && item.next_retry_at ? (
        <span className="text-ax-text-secondary">
          {t("admin_crawler_retry_after", { time: retryAt ?? "—" })}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Every website with a crawl schedule: when it was last crawled, when it is
 * next due and what keeps it waiting. Sorted by the server (one column, a
 * fixed direction per column), so the headers only pick the column.
 */
export function ScheduleTable({
  items,
  asOf,
  sort,
  filtered,
  onSort,
  onSelect
}: {
  items: CrawlerScheduledWebsite[];
  asOf: string;
  sort: ScheduleSort;
  filtered: boolean;
  onSort: (sort: ScheduleSort) => void;
  onSelect: (runId: string) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const sortState: TableSortState<ScheduleSort> = [
    { sortKey: sort, direction: SCHEDULE_SORT_DIRECTIONS[sort] }
  ];
  const sortPlugin = useTableSortable<CrawlerScheduledWebsite, ScheduleSort>({
    sort: sortState,
    onSortChange: (next) => onSort(next[0]?.sortKey ?? sort),
    allowUnsortedState: false
  });

  if (items.length === 0) {
    return (
      <EmptyState
        title={
          filtered ? t("admin_crawler_schedule_empty_filtered") : t("admin_crawler_schedule_empty")
        }
        headingLevel={3}
        isCompact
      />
    );
  }

  const columns: TableColumn<CrawlerScheduledWebsite>[] = [
    {
      key: "url",
      header: t("website"),
      width: proportional(3),
      sortable: true,
      renderCell: (item) => <WebsiteCell item={item} onSelect={onSelect} />
    },
    {
      key: "space",
      header: t("admin_crawler_space"),
      width: proportional(2),
      renderCell: (item) => item.space_name ?? "—"
    },
    {
      key: "interval",
      header: t("admin_crawler_interval"),
      width: pixel(130),
      renderCell: (item) => t(intervalLabelKey(item.update_interval))
    },
    {
      key: "last_crawled",
      header: t("admin_crawler_last_crawled"),
      width: proportional(2),
      sortable: true,
      renderCell: (item) => (
        <span className="flex flex-col items-start gap-1 text-xs">
          {item.last_crawled_at ? (
            <ClientTime value={item.last_crawled_at} format="date_time" />
          ) : (
            "—"
          )}
          {item.latest_run ? <CrawlRunStatusLabel run={item.latest_run} /> : null}
        </span>
      )
    },
    {
      key: "next_due",
      header: t("admin_crawler_next_due"),
      width: proportional(2),
      sortable: true,
      renderCell: (item) =>
        item.next_due_at ? (
          <span className="flex flex-col items-start gap-0.5 text-xs">
            <ClientTime value={item.next_due_at} format="date_time" />
            <span className="text-ax-text-secondary">
              {relativeDue(item.next_due_at, asOf, locale)}
            </span>
          </span>
        ) : (
          "—"
        )
    },
    {
      key: "state",
      header: t("status"),
      width: proportional(2),
      renderCell: (item) => <ScheduleStateCell item={item} />
    },
    {
      key: "failures",
      header: t("failures"),
      width: proportional(2),
      renderCell: (item) => <FailuresCell item={item} />
    }
  ];

  return (
    <Table
      data={items}
      columns={columns}
      idKey="website_id"
      aria-label={t("admin_crawler_schedule_caption")}
      plugins={{ sort: sortPlugin }}
      className="min-w-[1100px]"
    />
  );
}
