import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Switch } from "@astryxdesign/core/Switch";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { useInfiniteQuery } from "@tanstack/react-query";
import { MessagesSquare, Search } from "lucide-react";
import { useTranslations } from "use-intl";
import { useDeferredValue, useEffect, useId, useRef, useState } from "react";
import { KEYBOARD } from "@/components/astryx/keyboard-hints";
import { Table } from "@/components/astryx/table";
import { TextInput } from "@/components/astryx/text-input";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import type { InsightSource } from "@/features/insights/insight-figures";
import type { InsightRange } from "@/features/insights/insights-range";
import { SourceTag } from "@/features/insights/source-tag";
import { AnswerFeedbackCell } from "./answer-feedback-cell";
import {
  fetchAssistantQuestionHistory,
  insightPeriod,
  type AssistantInsightFilters,
  type AssistantInsightQuestion
} from "./insights";
import { QuestionDetails } from "./question-details";

/**
 * Opens the conversation a question was asked in, read-only in "Utforska
 * konversationer" as a cited conversation opens. Every row has one, so its
 * name adds the question's time, as the row's Skapad cell shows it.
 */
function ConversationButton({
  question,
  onOpen
}: {
  question: AssistantInsightQuestion;
  onOpen: (sessionId: string) => void;
}) {
  const t = useTranslations();
  const time = useClientTimeText(question.created_at, "date_time");
  return (
    <Button
      variant="ghost"
      size="sm"
      label={time ? t("insights_session_from", { time }) : t("session")}
      aria-haspopup="dialog"
      icon={<MessagesSquare className="size-4" aria-hidden="true" />}
      onClick={() => onOpen(question.session_id)}
    >
      {t("session")}
    </Button>
  );
}

/**
 * "Frågehistorik": the questions asked to an assistant in the period, with
 * how each answer was rated and the owner's comment, searchable and loaded a
 * page at a time. A question opens its logged record; its conversation opens
 * in "Utforska konversationer". Follow-up questions are included unless the
 * switch leaves them out. Each question says where its conversation came
 * from; `source` limits them to one source.
 */
export function QuestionHistory({
  assistantId,
  range,
  source = null,
  onOpenConversation
}: {
  assistantId: string;
  range: InsightRange;
  source?: InsightSource | null;
  onOpenConversation: (sessionId: string) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const headingId = useId();
  const [includeFollowups, setIncludeFollowups] = useState(true);
  const filters: AssistantInsightFilters = { ...insightPeriod(range), includeFollowups, source };
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<AssistantInsightQuestion | null>(null);
  const questionTrigger = useRef<HTMLButtonElement | null>(null);
  const deferredSearch = useDeferredValue(search.trim());

  const query = useInfiniteQuery({
    ...cursorPagination,
    queryKey: ["admin-insights-assistant-questions", assistantId, filters, deferredSearch],
    queryFn: ({ pageParam }) =>
      fetchAssistantQuestionHistory({
        api: browserApi,
        assistantId,
        filters,
        cursor: pageParam,
        query: deferredSearch || undefined
      })
  });
  const items = flattenPages(query.data?.pages);
  const total = query.data?.pages[0]?.total_count ?? 0;
  const countLabel = t("loaded_questions_count", { loaded: items.length, total });

  // Announce the count once a new search has its results (WCAG 4.1.3), not
  // on the first load.
  const announcedFor = useRef(deferredSearch);
  const settled = query.isSuccess && !query.isFetching;
  useEffect(() => {
    if (!settled || announcedFor.current === deferredSearch) return;
    announcedFor.current = deferredSearch;
    announce(countLabel);
  }, [announce, countLabel, deferredSearch, settled]);

  const columns: TableColumn<AssistantInsightQuestion>[] = [
    {
      key: "created_at",
      header: t("created"),
      width: pixel(176),
      renderCell: (item) => <ClientTime value={item.created_at} format="date_time" />
    },
    // Room for whole words: on a phone the table scrolls sideways instead.
    {
      key: "question",
      header: t("question"),
      width: proportional(1, { minWidth: 240 }),
      renderCell: (item) => (
        <Button
          variant="ghost"
          label={item.question || t("untitled")}
          className="max-w-full text-left whitespace-normal"
          onClick={(event) => {
            questionTrigger.current = event.currentTarget;
            setSelected(item);
          }}
        />
      )
    },
    {
      key: "source",
      header: t("insights_source_label"),
      width: pixel(112),
      renderCell: (item) => <SourceTag source={item.source} />
    },
    {
      key: "feedback",
      header: t("feedback_column"),
      width: proportional(0.5),
      renderCell: (item) => <AnswerFeedbackCell feedback={item.feedback} />
    },
    {
      key: "session_id",
      header: t("session"),
      width: pixel(136),
      renderCell: (item) => <ConversationButton question={item} onOpen={onOpenConversation} />
    }
  ];

  return (
    <Card className="flex flex-col gap-4">
      <section aria-labelledby={headingId} className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id={headingId} className="text-base font-semibold">
            {t("question_history")}
          </h2>
          <Switch
            label={t("include_follow_up_questions")}
            value={includeFollowups}
            onChange={setIncludeFollowups}
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 flex-1 basis-64">
            <TextInput
              label={t("search")}
              isLabelHidden
              placeholder={t("assistant_questions_search_placeholder")}
              startIcon={Search}
              {...KEYBOARD.search}
              value={search}
              onChange={setSearch}
              hasClear
              autoComplete="off"
              width="100%"
            />
          </div>
          <span className="text-ax-text-secondary text-sm">{countLabel}</span>
        </div>

        <QueryStateBoundary query={query} rows={5}>
          {() =>
            items.length === 0 ? (
              <p className="text-ax-text-secondary text-sm">
                {t("no_questions_found_current_settings")}
              </p>
            ) : (
              <Table
                aria-labelledby={headingId}
                data={items}
                columns={columns}
                idKey="id"
                verticalAlign="top"
              />
            )
          }
        </QueryStateBoundary>

        {!query.hasNextPage && items.length > 0 ? (
          <span className="text-ax-text-secondary self-end text-sm">
            {t("loaded_all_questions", { total })}
          </span>
        ) : null}
        <LoadMore query={query} label={t("load_more_questions")} />
      </section>
      {selected ? (
        <QuestionDetails
          key={selected.id}
          question={selected}
          triggerRef={questionTrigger}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </Card>
  );
}
