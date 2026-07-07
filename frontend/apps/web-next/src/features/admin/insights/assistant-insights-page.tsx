"use client";

import { useInfiniteQuery, useMutation, useQuery, useSuspenseQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Copy,
  ExternalLink,
  History,
  RotateCcw,
  Search,
  SendHorizontal
} from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { type Dispatch, type SetStateAction, useDeferredValue, useMemo, useState } from "react";
import { MessageResponse } from "@/components/ai-elements/message";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import {
  askAssistantInsightQuestion,
  assistantQuestionHistoryQueryOptions,
  fetchAssistantQuestionHistory,
  type AssistantInsightFilters
} from "./insights";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";

const NUMBER = new Intl.NumberFormat("sv-SE");

function isoFromDateInput(value: string, boundary: "start" | "end"): string {
  const time = boundary === "start" ? "00:00:00" : "23:59:59";
  return new Date(`${value}T${time}`).toISOString();
}

function defaultFilters(): AssistantInsightFilters {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 30);
  return { start: start.toISOString(), end: end.toISOString(), includeFollowups: true };
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="flex flex-col gap-1 p-4">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
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
  return (
    <Card className="flex flex-wrap items-end gap-3 p-4">
      <label className="flex flex-col gap-1 text-xs">
        {t("from")}
        <Input
          type="date"
          className="h-8 w-36"
          value={filters.start.slice(0, 10)}
          onChange={(event) => {
            if (!event.target.value) return;
            setFilters((current) => ({
              ...current,
              start: isoFromDateInput(event.target.value, "start")
            }));
          }}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        {t("to")}
        <Input
          type="date"
          className="h-8 w-36"
          value={filters.end.slice(0, 10)}
          onChange={(event) => {
            if (!event.target.value) return;
            setFilters((current) => ({
              ...current,
              end: isoFromDateInput(event.target.value, "end")
            }));
          }}
        />
      </label>
      <label className="flex min-h-8 items-center gap-2 text-sm">
        <Switch
          checked={filters.includeFollowups}
          onCheckedChange={(checked) =>
            setFilters((current) => ({ ...current, includeFollowups: checked }))
          }
        />
        {t("include_follow_up_questions")}
      </label>
      <Button variant="outline" size="sm" onClick={() => setFilters(defaultFilters())}>
        <RotateCcw className="size-4" />
        {t("reset")}
      </Button>
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
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [copied, setCopied] = useState(false);

  const ask = useMutation({
    mutationFn: (text: string) =>
      askAssistantInsightQuestion({ api: browserApi, assistantId, filters, question: text }),
    onSuccess: (text) => setAnswer(text)
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <Card className="flex min-h-96 flex-col gap-4 p-4">
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const text = question.trim();
            if (!text || ask.isPending) return;
            setAnswer("");
            setCopied(false);
            ask.mutate(text);
          }}
        >
          <Textarea
            rows={4}
            value={question}
            placeholder={t("ask_about_insights")}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.shiftKey) return;
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-muted-foreground text-xs">{t("insights_enter_hint")}</span>
            <Button type="submit" disabled={!question.trim() || ask.isPending}>
              <SendHorizontal className="size-4" />
              {ask.isPending ? t("loading") : t("submit_your_question")}
            </Button>
          </div>
        </form>

        <div className="bg-muted/30 flex min-h-52 flex-1 flex-col gap-3 rounded-lg border p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">{t("answer")}</p>
            {answer ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  void navigator.clipboard.writeText(answer);
                  setCopied(true);
                }}
              >
                <Copy className="size-4" />
                {copied ? t("copied") : t("copy")}
              </Button>
            ) : null}
          </div>
          {ask.isPending ? (
            <Skeleton className="h-28 w-full" />
          ) : ask.isError ? (
            <p className="text-destructive text-sm">{t("request_failed")}</p>
          ) : answer ? (
            <MessageResponse className="text-sm leading-7">{answer}</MessageResponse>
          ) : (
            <p className="text-muted-foreground text-sm">
              {t("ask_question_about_conversation_history")}
            </p>
          )}
        </div>
      </Card>

      <Card className="flex h-fit flex-col gap-3 p-4">
        <p className="font-medium">{t("included_timeframe")}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">{t("from")}</dt>
          <dd>{filters.start.slice(0, 10)}</dd>
          <dt className="text-muted-foreground">{t("to")}</dt>
          <dd>{filters.end.slice(0, 10)}</dd>
          <dt className="text-muted-foreground">{t("assistant")}</dt>
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
  const locale = useLocale();
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }),
    [locale]
  );

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

  return (
    <Card className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="relative flex min-w-64 flex-1 items-center">
          <Search className="text-muted-foreground absolute left-2.5 size-4" />
          <Input
            className="pl-8"
            value={search}
            placeholder={t("assistant_questions_search_placeholder")}
            aria-label={t("search")}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <span className="text-muted-foreground text-sm">
          {t("loaded_questions_count", { loaded: items.length, total })}
        </span>
      </div>

      {query.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : query.isError ? (
        <p className="text-destructive text-sm">{t("request_failed")}</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("no_questions_found_current_settings")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("created")}</TableHead>
              <TableHead>{t("question")}</TableHead>
              <TableHead>{t("session")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="text-muted-foreground text-sm">
                  {dateFormatter.format(new Date(item.created_at))}
                </TableCell>
                <TableCell className="max-w-xl whitespace-normal">{item.question}</TableCell>
                <TableCell>
                  <Button variant="ghost" size="sm" asChild>
                    <Link href={`/dashboard/${assistantId}/${item.session_id}`}>
                      <ExternalLink className="size-4" />
                      {t("session")}
                    </Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <div className="flex items-center justify-end gap-2">
        {!query.hasNextPage && items.length > 0 ? (
          <span className="text-muted-foreground text-sm">
            {t("loaded_all_questions", { total })}
          </span>
        ) : null}
        <Button
          variant="outline"
          size="sm"
          disabled={!query.hasNextPage || query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? t("loading") : t("load_more_questions")}
        </Button>
      </div>
    </Card>
  );
}

export function AssistantInsightsPage({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const [filters, setFilters] = useState(defaultFilters);
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));
  const stats = useQuery(
    assistantQuestionHistoryQueryOptions({ api: browserApi, assistantId, filters, limit: 1 })
  );
  const count = stats.data?.total_count;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader title={assistant.name}>
        <Button variant="outline" asChild>
          <Link href="/admin/insights">
            <BarChart3 className="size-4" />
            {t("insights")}
          </Link>
        </Button>
      </PageHeader>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("assistant")} value={assistant.name} />
        <Stat
          label={t("question_history")}
          value={count == null ? t("loading") : NUMBER.format(count)}
        />
        <Stat
          label={t("include_follow_up_questions")}
          value={filters.includeFollowups ? t("yes") : t("no")}
        />
      </div>

      <FilterBar filters={filters} setFilters={setFilters} />

      <Tabs defaultValue="analysis">
        <TabsList>
          <TabsTrigger value="analysis">
            <BarChart3 className="size-4" />
            {t("analyse")}
          </TabsTrigger>
          <TabsTrigger value="questions">
            <History className="size-4" />
            {t("question_history")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="analysis" className="pt-4">
          <AnalysisTab assistantId={assistantId} assistantName={assistant.name} filters={filters} />
        </TabsContent>
        <TabsContent value="questions" className="pt-4">
          <QuestionsTab assistantId={assistantId} filters={filters} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
