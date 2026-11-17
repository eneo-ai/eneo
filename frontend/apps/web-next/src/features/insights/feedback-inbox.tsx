import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { List, ListItem } from "@astryxdesign/core/List";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { useInfiniteQuery } from "@tanstack/react-query";
import { MessagesSquare, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import type { ChatPartner } from "@/lib/chat/types";
import { insightSourceQuery, type InsightFilters, type InsightRating } from "./insight-figures";
import { insightPartnerQuery, insightRangeParams } from "./insights-range";
import { SourceTag } from "./source-tag";

const PAGE_SIZE = 20;

/** The inbox's filter: every rating, the bad ones someone explained, or the good ones. */
type FeedbackFilter = "all" | "bad_commented" | "good";

const FILTER_QUERY: Record<FeedbackFilter, { value?: 1 | -1; has_comment?: boolean }> = {
  all: {},
  bad_commented: { value: -1, has_comment: true },
  good: { value: 1 }
};

function isFeedbackFilter(value: string): value is FeedbackFilter {
  return value in FILTER_QUERY;
}

/** A rating's identity: one per rated answer, and one per rated conversation. */
const ratingKey = (rating: InsightRating) =>
  `${rating.kind}:${rating.question_id ?? rating.session_id}`;

function RatingRow({
  rating,
  questionId,
  onOpenConversation
}: {
  rating: InsightRating;
  questionId: string;
  onOpenConversation: (sessionId: string) => void;
}) {
  const t = useTranslations();
  const good = rating.value === 1;
  const Icon = good ? ThumbsUp : ThumbsDown;
  return (
    <ListItem
      data-rating-row={ratingKey(rating)}
      align="start"
      label={
        rating.comment ? (
          <span className="block font-medium break-words whitespace-normal">
            {t("insights_feedback_comment", { comment: rating.comment })}
          </span>
        ) : (
          <span className="text-ax-text-secondary block">{t("insights_feedback_no_comment")}</span>
        )
      }
      description={
        <span className="flex flex-col gap-1.5">
          <span id={questionId} className="break-words whitespace-normal">
            {t("insights_feedback_question", { question: rating.question })}
          </span>
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-1.5">
              <Icon
                aria-hidden="true"
                className={good ? "text-ax-success size-4" : "text-ax-error size-4"}
              />
              {t("insights_feedback_rating", {
                value: good ? "good" : "bad",
                kind: rating.kind
              })}
            </span>
            <SourceTag source={rating.source} />
            <ClientTime value={rating.created_at} format="date" />
          </span>
        </span>
      }
      endContent={
        <Button
          size="sm"
          variant="secondary"
          label={t("insights_feedback_open")}
          icon={<MessagesSquare className="size-4" aria-hidden="true" />}
          aria-haspopup="dialog"
          aria-describedby={questionId}
          onClick={() => onOpenConversation(rating.session_id)}
        />
      }
    />
  );
}

/**
 * "Återkoppling från användarna": the period's ratings of an assistant's or
 * group chat's answers and of whole conversations, newest first and a page
 * at a time, filtered to the bad ones with a comment or the good ones. A row
 * says what was rated and how, the comment, the question it was about and
 * where the conversation came from; never who rated it. "Läs konversationen"
 * opens the conversation in "Utforska konversationer".
 */
export function FeedbackInbox({
  partner,
  filters,
  onOpenConversation
}: {
  partner: Pick<ChatPartner, "type" | "id">;
  filters: InsightFilters;
  onOpenConversation: (sessionId: string) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const headingId = useId();
  const rowId = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState<FeedbackFilter>("all");
  const { startTime, endTime } = insightRangeParams(filters.range);
  const query = {
    ...insightPartnerQuery(partner),
    start_time: startTime,
    end_time: endTime,
    ...insightSourceQuery(filters.source),
    ...FILTER_QUERY[filter],
    limit: PAGE_SIZE
  };

  const ratings = useInfiniteQuery({
    ...cursorPagination,
    queryKey: ["conversation-insights", "feedback", partner.type, partner.id, query],
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/feedback/", {
          params: { query: { ...query, cursor: pageParam } },
          signal
        })
      )
  });
  const pages = ratings.data?.pages;
  const rows = flattenPages(pages);
  const total = pages?.[0]?.total_count ?? rows.length;
  const shown = t("insights_shown_of_total", { shown: rows.length, total });

  // Announce what a new filter found once it is in (WCAG 4.1.3), not the
  // first load; an empty result announces itself (EmptyState).
  const announcedFor = useRef(filter);
  const settled = ratings.isSuccess && !ratings.isFetching;
  useEffect(() => {
    if (!settled || announcedFor.current === filter) return;
    announcedFor.current = filter;
    if (total > 0) announce(shown);
  }, [announce, filter, settled, shown, total]);

  // "Visa fler": once the page it asked for renders, focus that page's first
  // row (the button itself goes away with the last page).
  const focusPage = useRef<number | null>(null);
  const pageCount = pages?.length ?? 0;
  useEffect(() => {
    const page = focusPage.current;
    if (page === null || pageCount <= page) return;
    focusPage.current = null;
    const first = pages?.[page]?.items[0];
    if (!first) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-rating-row="${CSS.escape(ratingKey(first))}"] button`)
      ?.focus();
  }, [pageCount, pages]);

  return (
    <Card>
      <section aria-labelledby={headingId} className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id={headingId} className="text-base font-semibold">
            {t("insights_feedback_heading")}
          </h2>
          <div className="max-w-full min-w-0">
            <SegmentedControl
              label={t("insights_feedback_filter_label")}
              value={filter}
              onChange={(value) => {
                if (isFeedbackFilter(value)) setFilter(value);
              }}
              size="sm"
            >
              <SegmentedControlItem value="all" label={t("all")} />
              <SegmentedControlItem
                value="bad_commented"
                label={t("insights_feedback_bad_with_comment")}
              />
              <SegmentedControlItem value="good" label={t("insights_feedback_good")} />
            </SegmentedControl>
          </div>
        </div>
        <QueryStateBoundary query={ratings} rows={3}>
          {() =>
            rows.length === 0 ? (
              <EmptyState
                title={t("insights_feedback_empty")}
                headingLevel={3}
                isCompact
                framed={false}
              />
            ) : (
              <div ref={listRef} className="flex flex-col gap-3">
                <List hasDividers edge="bleed" aria-labelledby={headingId}>
                  {rows.map((rating, index) => (
                    <RatingRow
                      key={ratingKey(rating)}
                      rating={rating}
                      questionId={`${rowId}-${index}`}
                      onOpenConversation={onOpenConversation}
                    />
                  ))}
                </List>
                <div className="text-ax-text-secondary flex flex-col items-center gap-2 text-sm">
                  <LoadMore
                    query={ratings}
                    label={t("insights_show_more")}
                    onLoad={() => {
                      focusPage.current = pageCount;
                      void ratings.fetchNextPage();
                    }}
                  />
                  <span>{shown}</span>
                </div>
              </div>
            )
          }
        </QueryStateBoundary>
      </section>
    </Card>
  );
}
