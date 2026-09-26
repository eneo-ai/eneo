"use client";

import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { DateInput } from "@astryxdesign/core/DateInput";
import { useAnnounce, useClipboard } from "@astryxdesign/core/hooks";
import { Switch } from "@astryxdesign/core/Switch";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { pixel, proportional, Table, type TableColumn } from "@astryxdesign/core/Table";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useInfiniteQuery, useMutation, useQuery, useSuspenseQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Check,
  Copy,
  ExternalLink,
  History,
  RotateCcw,
  Search,
  SendHorizontal
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import {
  type Dispatch,
  type SetStateAction,
  useDeferredValue,
  useEffect,
  useId,
  useRef,
  useState
} from "react";
import { MessageResponse } from "@/components/ai-elements/message";
import { ClientTime } from "@/components/composites/client-time";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import { toast } from "@/lib/toast";
import {
  askAssistantInsightQuestion,
  assistantQuestionHistoryQueryOptions,
  fetchAssistantQuestionHistory,
  isoFromDateInput,
  localDate,
  type AssistantInsightFilters,
  type AssistantInsightQuestion
} from "./insights";
import { AnswerFeedbackCell } from "./answer-feedback-cell";
import { AnswerFeedbackSummary } from "./answer-feedback-summary";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";

type InsightsTab = "analysis" | "questions";

function defaultFilters(): AssistantInsightFilters {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 30);
  return { start: start.toISOString(), end: end.toISOString(), includeFollowups: true };
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="flex flex-col gap-1">
      <dt className="text-ax-text-secondary text-sm">{label}</dt>
      <dd className="text-2xl font-semibold wrap-anywhere tabular-nums">{value}</dd>
    </Card>
  );
}

function FilterBar({
  filters,
  setFilters
}: {
  filters: AssistantInsightFilters;
  setFilters: Dispatch<SetStateAction<AssistantInsightFilters>>;
}) {
  const t = useTranslations();
  // Astryx's own calendar everywhere: the native picker it uses on touch
  // probes the engine with a <style> element, which the production CSP blocks
  // (AGENTS.md → CSP).
  const dateField = (boundary: "start" | "end") => (
    <DateInput
      label={boundary === "start" ? t("from") : t("to")}
      value={localDate(boundary === "start" ? filters.start : filters.end)}
      onChange={(value) => {
        if (!value) return;
        setFilters((current) => ({ ...current, [boundary]: isoFromDateInput(value, boundary) }));
      }}
      nativePicker="never"
      weekStartsOn="mon"
      format="date"
      width="11rem"
    />
  );

  return (
    <Card className="flex flex-wrap items-end gap-3">
      {dateField("start")}
      {dateField("end")}
      <Switch
        label={t("include_follow_up_questions")}
        value={filters.includeFollowups}
        onChange={(checked) => setFilters((current) => ({ ...current, includeFollowups: checked }))}
      />
      <Button
        label={t("reset")}
        icon={<RotateCcw className="size-4" aria-hidden="true" />}
        onClick={() => setFilters(defaultFilters())}
      />
    </Card>
  );
}

function AnalysisTab({
  assistantId,
  assistantName,
  filters
}: {
  assistantId: string;
  assistantName: string;
  filters: AssistantInsightFilters;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const { copy, isCopied } = useClipboard({ announce: t("copied_to_clipboard") });

  const ask = useMutation({
    mutationFn: (text: string) =>
      askAssistantInsightQuestion({ api: browserApi, assistantId, filters, question: text }),
    // The answer can take a while and appears away from focus (WCAG 4.1.3).
    onSuccess: (text) => {
      setAnswer(text);
      announce(t("chat_announce_answer_ready"));
    },
    onError: () => announce(t("request_failed"))
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <Card className="flex min-h-96 flex-col gap-4">
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const text = question.trim();
            if (!text || ask.isPending) return;
            setAnswer("");
            ask.mutate(text);
          }}
        >
          <TextArea
            label={t("ask_about_insights")}
            description={t("insights_enter_hint")}
            rows={4}
            value={question}
            onChange={setQuestion}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
              event.preventDefault();
              event.currentTarget.closest("form")?.requestSubmit();
            }}
          />
          <Button
            type="submit"
            variant="primary"
            label={t("submit_your_question")}
            icon={<SendHorizontal className="size-4" aria-hidden="true" />}
            isDisabled={!question.trim()}
            // Stays focusable while the answer is prepared (a second submit is ignored).
            isLoading={ask.isPending}
            isInterruptible
            className="self-end"
          />
        </form>

        <div className="bg-ax-sunken border-ax-border rounded-ax-container flex min-h-52 flex-1 flex-col gap-3 border p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">{t("answer")}</p>
            {answer ? (
              <Button
                variant="ghost"
                size="sm"
                label={isCopied ? t("copied") : t("copy")}
                icon={
                  isCopied ? (
                    <Check className="size-4" aria-hidden="true" />
                  ) : (
                    <Copy className="size-4" aria-hidden="true" />
                  )
                }
                onClick={async () => {
                  if (!(await copy(answer))) toast.error(t("chat_copy_failed"));
                }}
              />
            ) : null}
          </div>
          {ask.isPending ? (
            <LoadingState variant="text" rows={3} label={t("chat_insights_generating")} />
          ) : ask.isError ? (
            <p className="text-ax-error text-sm">{t("request_failed")}</p>
          ) : answer ? (
            <MessageResponse className="text-sm leading-7">{answer}</MessageResponse>
          ) : (
            <p className="text-ax-text-secondary text-sm">
              {t("ask_question_about_conversation_history")}
            </p>
          )}
        </div>
      </Card>

      <Card className="flex h-fit flex-col gap-3">
        <p className="font-medium">{t("included_timeframe")}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-ax-text-secondary">{t("from")}</dt>
          <dd>
            <ClientTime value={filters.start} format="date" />
          </dd>
          <dt className="text-ax-text-secondary">{t("to")}</dt>
          <dd>
            <ClientTime value={filters.end} format="date" />
          </dd>
          <dt className="text-ax-text-secondary">{t("assistant")}</dt>
          <dd className="truncate">{assistantName}</dd>
        </dl>
      </Card>
    </div>
  );
}

function QuestionsTab({
  assistantId,
  filters
}: {
  assistantId: string;
  filters: AssistantInsightFilters;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [search, setSearch] = useState("");
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
    { key: "question", header: t("question"), width: proportional(1, { minWidth: 240 }) },
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
      renderCell: (item) => (
        <Button
          href={`/dashboard/${assistantId}/${item.session_id}`}
          variant="ghost"
          size="sm"
          label={t("session")}
          icon={<ExternalLink className="size-4" aria-hidden="true" />}
        />
      )
    }
  ];

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <TextInput
            label={t("search")}
            isLabelHidden
            placeholder={t("assistant_questions_search_placeholder")}
            startIcon={Search}
            value={search}
            onChange={setSearch}
            hasClear
            autoComplete="off"
            width="100%"
          />
        </div>
        <span className="text-ax-text-secondary text-sm">{countLabel}</span>
      </div>

      {query.isPending ? (
        <LoadingState rows={5} />
      ) : query.isError ? (
        <p className="text-ax-error text-sm">{t("request_failed")}</p>
      ) : items.length === 0 ? (
        <p className="text-ax-text-secondary text-sm">{t("no_questions_found_current_settings")}</p>
      ) : (
        <Table
          aria-label={t("question_history")}
          data={items}
          columns={columns}
          idKey="id"
          verticalAlign="top"
        />
      )}

      <div className="flex items-center justify-end gap-2">
        {!query.hasNextPage && items.length > 0 ? (
          <span className="text-ax-text-secondary text-sm">
            {t("loaded_all_questions", { total })}
          </span>
        ) : null}
        <Button
          label={t("load_more_questions")}
          isDisabled={!query.hasNextPage}
          // Stays focusable while the next page loads.
          isLoading={query.isFetchingNextPage}
          isInterruptible
          onClick={() => {
            if (!query.isFetchingNextPage) void query.fetchNextPage();
          }}
        />
      </div>
    </Card>
  );
}

export function AssistantInsightsPage({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const format = useFormatter();
  const [filters, setFilters] = useState(defaultFilters);
  const [tab, setTab] = useState<InsightsTab>("analysis");
  // Panels stay mounted once opened (hidden when inactive), so a question and
  // its answer survive a look at the history; the history loads on first visit.
  const [visited, setVisited] = useState<ReadonlySet<InsightsTab>>(() => new Set(["analysis"]));
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));
  const stats = useQuery(
    assistantQuestionHistoryQueryOptions({ api: browserApi, assistantId, filters, limit: 1 })
  );
  const count = stats.data?.total_count;

  const baseId = useId();
  const tabId = (value: InsightsTab) => `${baseId}-tab-${value}`;
  const panelId = (value: InsightsTab) => `${baseId}-panel-${value}`;

  function selectTab(next: InsightsTab) {
    setTab(next);
    setVisited((current) => (current.has(next) ? current : new Set([...current, next])));
  }

  const panel = (value: InsightsTab, content: React.ReactNode) => (
    <div
      role="tabpanel"
      id={panelId(value)}
      aria-labelledby={tabId(value)}
      hidden={tab !== value}
      className="pt-4"
    >
      {visited.has(value) ? content : null}
    </div>
  );

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader
        title={assistant.name}
        actions={
          <Button
            href="/admin/insights"
            label={t("insights")}
            icon={<BarChart3 className="size-4" aria-hidden="true" />}
          />
        }
      />

      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("assistant")} value={assistant.name} />
        <Stat
          label={t("question_history")}
          value={count == null ? t("loading") : format.number(count)}
        />
        <Stat
          label={t("include_follow_up_questions")}
          value={filters.includeFollowups ? t("yes") : t("no")}
        />
      </dl>
      <AnswerFeedbackSummary assistantId={assistantId} filters={filters} />

      <FilterBar filters={filters} setFilters={setFilters} />

      <div className="flex flex-col">
        <TabList
          role="tablist"
          aria-label={t("legacy_insights_tabs_label")}
          value={tab}
          onChange={(value) => selectTab(value === "questions" ? "questions" : "analysis")}
          hasDivider
        >
          <Tab
            id={tabId("analysis")}
            value="analysis"
            label={t("analyse")}
            icon={<BarChart3 className="size-4" aria-hidden="true" />}
            panelId={panelId("analysis")}
          />
          <Tab
            id={tabId("questions")}
            value="questions"
            label={t("question_history")}
            icon={<History className="size-4" aria-hidden="true" />}
            panelId={panelId("questions")}
          />
        </TabList>
        {panel(
          "analysis",
          <AnalysisTab assistantId={assistantId} assistantName={assistant.name} filters={filters} />
        )}
        {panel("questions", <QuestionsTab assistantId={assistantId} filters={filters} />)}
      </div>
    </div>
  );
}
