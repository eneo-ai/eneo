import { Card } from "@astryxdesign/core/Card";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Link } from "@astryxdesign/core/Link";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { pixel, proportional, useTableSortable, type TableColumn } from "@astryxdesign/core/Table";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState } from "react";
import { KEYBOARD } from "@/components/astryx/keyboard-hints";
import { Table } from "@/components/astryx/table";
import { TextInput } from "@/components/astryx/text-input";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { flattenPages } from "@/lib/api/pagination";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import {
  countChange,
  INSIGHT_SOURCES,
  share,
  sourceParts,
  type InsightSource,
  type SourceCounts
} from "@/features/insights/insight-figures";
import type { InsightRange } from "@/features/insights/insights-range";
import { PeriodChange } from "@/features/insights/period-change";
import { SOURCE_STYLE, SourceLegend } from "@/features/insights/source-tag";
import {
  fetchInsightTargets,
  INSIGHT_TARGETS_SEARCH_MAX,
  nextTargetOffset,
  type InsightTarget,
  type InsightTargetSort
} from "./insights";

type TargetRow = InsightTarget & { key: string };
type SortKey = InsightTargetSort["by"];

/** A source's share of a target's conversations: "58 % användare". */
const SHARE_KEY = {
  user: "insights_share_user",
  widget: "insights_share_widget",
  api_key: "insights_share_api_key"
} as const satisfies Record<InsightSource, string>;

/** The target's own insights page, on the overview's period. */
function insightsHref(target: InsightTarget, range: InsightRange, compare: boolean): string {
  const kind = target.kind === "group_chat" ? "group-chat" : "assistant";
  const search = new URLSearchParams({ from: range.start, to: range.end });
  if (compare) search.set("compare", "1");
  return `/admin/insights/${kind}/${target.id}?${search.toString()}`;
}

/** Where the target's insights switch is: its editor's publishing section. */
function settingHref(target: InsightTarget): string {
  const kind = target.kind === "group_chat" ? "group-chats" : "assistants";
  return `/spaces/${target.space_id}/${kind}/${target.id}/edit?section=publishing#publishing`;
}

/** Each source's share of the conversations as a stacked bar, named in words. */
function SourceBar({ counts }: { counts: SourceCounts }) {
  const t = useTranslations();
  const format = useFormatter();
  const parts = sourceParts(counts);
  if (parts.length === 0) {
    return <span className="text-ax-text-secondary text-sm">{t("insights_targets_no_usage")}</span>;
  }
  const label = parts
    .map(({ source, count }) =>
      t(SHARE_KEY[source], {
        share: format.number(share(count, counts.total) ?? 0, { style: "percent" })
      })
    )
    .join(", ");
  return (
    <div
      role="img"
      aria-label={label}
      title={label}
      className="flex h-2 w-28 max-w-full gap-0.5 overflow-hidden rounded-full"
    >
      {parts.map(({ source, count }) => (
        <div
          key={source}
          className={SOURCE_STYLE[source].fillClass}
          style={{ width: `${(share(count, counts.total) ?? 0) * 100}%` }}
        />
      ))}
    </div>
  );
}

/** Good answer ratings of all of them; usage only where insights are off. */
function RatingsCell({ target }: { target: InsightTarget }) {
  const t = useTranslations();
  const format = useFormatter();
  if (target.ratings === null) {
    return (
      <span className="text-ax-text-secondary flex flex-col items-end gap-0.5 text-sm">
        {t("insights_off_title")}
        {/* A personal assistant's editor is its owner's: there is nowhere to send an admin. */}
        {target.personal_space ? null : (
          <Link
            href={settingHref(target)}
            hasUnderline
            className="inline-flex items-center pointer-coarse:min-h-11"
          >
            {t("insights_targets_open_setting")}
          </Link>
        )}
      </span>
    );
  }
  const { positive, negative } = target.ratings;
  const good = share(positive, positive + negative);
  return good === null ? (
    <span className="text-ax-text-secondary text-sm">{t("insights_no_ratings")}</span>
  ) : (
    <span className="tabular-nums">{format.number(good, { style: "percent" })}</span>
  );
}

/**
 * "Assistenter och gruppchattar": every assistant and group chat of the
 * organisation with its use in the period, sorted, searched and filtered on
 * the server and loaded a page at a time. The name opens the target's
 * insights; a target with insights off shows its use only, with the way to
 * the setting. With `compare`, conversations carry their change.
 */
export function InsightTargets({ range, compare }: { range: InsightRange; compare: boolean }) {
  const t = useTranslations();
  const format = useFormatter();
  const announce = useAnnounce();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const [sort, setSort] = useState<InsightTargetSort>({ by: "conversations", order: "desc" });
  const [unusedOnly, setUnusedOnly] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  // The name search is sent once typing pauses.
  const search = useDebouncedValue(searchInput.trim().slice(0, INSIGHT_TARGETS_SEARCH_MAX));

  const targets = useInfiniteQuery({
    queryKey: ["admin-insights-targets", range, compare, sort, search, unusedOnly],
    initialPageParam: 0,
    getNextPageParam: nextTargetOffset,
    queryFn: ({ pageParam, signal }) =>
      fetchInsightTargets({
        api: browserApi,
        range,
        compare,
        sort,
        search,
        unusedOnly,
        offset: pageParam,
        signal
      }),
    // A new sort or search keeps the table (and the focus in it) until the new rows are in.
    placeholderData: keepPreviousData
  });
  const pages = targets.data?.pages;
  const rows: TargetRow[] = flattenPages(pages).map((target) => ({
    ...target,
    key: `${target.kind}:${target.id}`
  }));
  const total = pages?.[0]?.total_count ?? rows.length;
  const shown = t("insights_shown_of_total", { shown: rows.length, total });
  const settled = targets.isSuccess && !targets.isFetching && !targets.isPlaceholderData;

  // Announce the result of a new search, filter or sort once it is in (WCAG 4.1.3); not the first load.
  const resultsFor = [search, unusedOnly, sort.by, sort.order].join("|");
  const announcedFor = useRef(resultsFor);
  useEffect(() => {
    if (!settled || announcedFor.current === resultsFor) return;
    announcedFor.current = resultsFor;
    announce(shown);
  }, [announce, resultsFor, settled, shown]);

  // "Visa fler": once the page it asked for renders, focus the first new
  // row's first link, or the heading when that row has none (the button goes
  // away with the last page).
  const focusPage = useRef<number | null>(null);
  const pageCount = pages?.length ?? 0;
  useEffect(() => {
    const page = focusPage.current;
    if (page === null || pageCount <= page) return;
    focusPage.current = null;
    const first = pages?.slice(0, page).reduce((count, loaded) => count + loaded.items.length, 0);
    const row = tableRef.current?.querySelectorAll("tbody tr")[first ?? 0];
    (row?.querySelector<HTMLElement>("a[href]") ?? headingRef.current)?.focus();
  }, [pageCount, pages]);

  const sortPlugin = useTableSortable<TargetRow, SortKey>({
    // A server-sorted list always has one sort: a click on the active column
    // flips it instead of clearing it.
    allowUnsortedState: false,
    sort: [{ sortKey: sort.by, direction: sort.order === "asc" ? "ascending" : "descending" }],
    onSortChange: ([next]) => {
      if (!next) return;
      // A new column starts with names A to Z and figures largest first.
      setSort(
        next.sortKey !== sort.by
          ? { by: next.sortKey, order: next.sortKey === "name" ? "asc" : "desc" }
          : { by: next.sortKey, order: next.direction === "ascending" ? "asc" : "desc" }
      );
    }
  });

  const columns: TableColumn<TargetRow>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(1, { minWidth: 220 }),
      sortable: true,
      renderCell: (target) => {
        const where = target.personal_space ? t("personal_assistant") : target.space_name;
        return (
          <span className="flex min-w-0 flex-col items-start gap-0.5">
            {target.ratings === null ? (
              <span className="font-medium break-words">{target.name}</span>
            ) : (
              <Link
                href={insightsHref(target, range, compare)}
                className="inline-flex items-center font-medium break-words pointer-coarse:min-h-11"
              >
                {target.name}
              </Link>
            )}
            <span className="text-ax-text-secondary text-xs">
              {target.kind === "group_chat"
                ? t("insights_targets_group_chat_in", { space: where })
                : where}
            </span>
          </span>
        );
      }
    },
    {
      key: "conversations",
      header: t("insights_tile_conversations"),
      width: pixel(168),
      align: "end",
      sortable: true,
      renderCell: (target) => (
        <span className="flex flex-col items-end">
          <span className="tabular-nums">{format.number(target.conversations.total)}</span>
          {compare ? (
            <PeriodChange
              change={countChange(target.conversations.total, target.previous?.conversations.total)}
              unit="percent"
              compact
            />
          ) : null}
        </span>
      )
    },
    {
      key: "sources",
      header: t("insights_targets_sources"),
      width: pixel(144),
      renderCell: (target) => <SourceBar counts={target.conversations} />
    },
    {
      key: "questions",
      header: t("questions"),
      width: pixel(104),
      align: "end",
      sortable: true,
      renderCell: (target) => (
        <span className="tabular-nums">{format.number(target.questions)}</span>
      )
    },
    {
      key: "ratings",
      header: t("feedback_good_answers"),
      width: pixel(176),
      align: "end",
      renderCell: (target) => <RatingsCell target={target} />
    }
  ];

  return (
    <Card>
      <section aria-labelledby={headingId} className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2
            id={headingId}
            ref={headingRef}
            tabIndex={-1}
            className="text-base font-semibold focus:outline-none"
          >
            {t("insights_targets_heading")}
          </h2>
          <div className="flex max-w-full min-w-0 flex-wrap items-center gap-3">
            <SegmentedControl
              label={t("insights_targets_filter_label")}
              value={unusedOnly ? "unused" : "all"}
              onChange={(value) => setUnusedOnly(value === "unused")}
              size="sm"
            >
              <SegmentedControlItem value="all" label={t("all")} />
              <SegmentedControlItem value="unused" label={t("insights_targets_unused")} />
            </SegmentedControl>
            <div className="min-w-0 flex-1 basis-56">
              <TextInput
                label={t("insights_targets_search")}
                isLabelHidden
                placeholder={t("insights_targets_search")}
                startIcon={Search}
                {...KEYBOARD.search}
                value={searchInput}
                onChange={setSearchInput}
                hasClear
                autoComplete="off"
                width="100%"
              />
            </div>
          </div>
        </div>
        <QueryStateBoundary query={targets} rows={5} height={56}>
          {() =>
            rows.length === 0 ? (
              <p className="text-ax-text-secondary text-sm">{t("insights_targets_empty")}</p>
            ) : (
              <div
                className="flex flex-col gap-3"
                aria-busy={targets.isPlaceholderData || undefined}
              >
                <Table
                  ref={tableRef}
                  aria-labelledby={headingId}
                  data={rows}
                  columns={columns}
                  idKey="key"
                  verticalAlign="top"
                  pinnedColumn="name"
                  plugins={{ sort: sortPlugin }}
                  className="[--table-sticky-background:var(--color-ax-card)]"
                />
                <div className="text-ax-text-secondary flex flex-wrap items-center justify-between gap-3 text-sm">
                  <SourceLegend sources={INSIGHT_SOURCES} />
                  <span className="tabular-nums">{shown}</span>
                </div>
                <LoadMore
                  query={targets}
                  label={t("insights_show_more")}
                  onLoad={() => {
                    focusPage.current = pageCount;
                    void targets.fetchNextPage();
                  }}
                />
              </div>
            )
          }
        </QueryStateBoundary>
      </section>
    </Card>
  );
}
