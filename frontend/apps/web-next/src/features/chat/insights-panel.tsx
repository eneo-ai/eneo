"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQuery } from "@tanstack/react-query";
import { History, SendHorizontal, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";
import { ExploreConversationsDialog } from "@/features/insights/explore-conversations-dialog";
import {
  DEFAULT_INSIGHT_DAYS,
  insightPartnerQuery,
  insightRangeOfDays,
  insightRangeParams,
  type InsightRange
} from "@/features/insights/insights-range";
import { InsightsRangePicker } from "@/features/insights/insights-range-picker";

type InsightPartner = Extract<ChatPartner["type"], "assistant" | "group-chat">;

/** How long to wait for an asynchronous insight job, polled once a second. */
const MAX_POLLS = 120;

function stringField(value: unknown, key: string): string | null {
  if (typeof value !== "object" || value === null) return null;
  const field = (value as Record<string, unknown>)[key];
  return typeof field === "string" ? field : null;
}

function booleanField(value: unknown, key: string): boolean {
  if (typeof value !== "object" || value === null) return false;
  return (value as Record<string, unknown>)[key] === true;
}

/** Waits `ms`, or rejects as soon as `signal` aborts. */
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true }
    );
  });
}

/** The answer of an insight question, polling its job when it runs asynchronously. */
async function resolveInsightAnswer(response: unknown, signal: AbortSignal): Promise<string> {
  const immediate = stringField(response, "answer");
  if (immediate && !booleanField(response, "is_async")) return immediate;

  const jobId = stringField(response, "job_id") ?? stringField(response, "jobId");
  if (!jobId) return immediate ?? "";

  for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
    const status = await unwrap(
      browserApi.GET("/api/v1/analysis/conversation-insights/jobs/{job_id}/", {
        params: { path: { job_id: jobId } },
        signal
      })
    );
    if (status.status === "completed") return status.answer ?? "";
    if (status.status === "failed") throw new Error(status.error ?? "Failed");
    await wait(1000, signal);
  }

  throw new Error("Timed out");
}

function Stat({ label, value }: { label: React.ReactNode; value: number }) {
  return (
    <div className="border-ax-border rounded-ax-container border p-4">
      <dt className="text-ax-text-secondary inline-flex items-center gap-1.5 text-sm">{label}</dt>
      <dd className="mt-1 text-3xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * Insikter for an assistant or group chat: a period (the last 30 days to
 * begin with), its conversation and question counts and how the answers
 * were rated, the conversations themselves behind "Utforska konversationer",
 * and a question about those conversations. The answer is announced when it
 * is ready (it can take a while: the backend may run it as a job); leaving
 * the view stops waiting for it.
 */
export function InsightsPanel({ partner }: { partner: ChatPartner & { type: InsightPartner } }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [range, setRange] = useState<InsightRange>(() => insightRangeOfDays(DEFAULT_INSIGHT_DAYS));
  const [exploring, setExploring] = useState(false);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState(false);
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const questionProblem = asked && !question.trim() ? t("required_field") : null;
  const [answer, setAnswer] = useState("");
  const params = insightRangeParams(range);
  const query = insightPartnerQuery(partner);
  const request = useRef<AbortController | null>(null);

  // Stop polling a job when the view goes away.
  useEffect(() => () => request.current?.abort(), []);

  const stats = useQuery({
    queryKey: [
      "conversation-insights",
      "stats",
      partner.type,
      partner.id,
      params.fromDate,
      params.toDate
    ],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/", {
          params: {
            query: { start_time: params.startTime, end_time: params.endTime, ...query }
          },
          signal
        })
      )
  });

  const ask = useMutation({
    mutationFn: async (text: string) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      const response = await unwrap(
        browserApi.POST("/api/v1/analysis/conversation-insights/", {
          params: {
            query: {
              from_date: params.fromDate,
              to_date: params.toDate,
              processing_mode: "auto",
              ...query
            }
          },
          body: { question: text },
          signal: controller.signal
        })
      );
      return resolveInsightAnswer(response, controller.signal);
    },
    onSuccess: (text) => {
      setAnswer(text);
      announce(t("chat_announce_answer_ready"));
    },
    onError: () => {
      // Aborted because the view closed: nobody is waiting for the answer.
      if (request.current?.signal.aborted) return;
      announce(t("request_failed"));
    }
  });

  return (
    <div className="mx-auto flex w-full max-w-[712px] flex-1 flex-col gap-5 overflow-y-auto px-4 py-6">
      <InsightsRangePicker value={range} onChange={setRange} />

      <QueryStateBoundary query={stats} rows={2}>
        {(data) => (
          <dl className="grid gap-3 sm:grid-cols-2">
            <Stat label={t("total_conversations")} value={data.total_conversations} />
            <Stat label={t("total_questions")} value={data.total_questions} />
            {/* Ratings of single answers; a rating of a whole conversation is not counted. */}
            <Stat
              label={
                <>
                  <ThumbsUp aria-hidden="true" className="text-ax-success size-4" />
                  {t("feedback_good_answers")}
                </>
              }
              value={data.feedback.positive}
            />
            <Stat
              label={
                <>
                  <ThumbsDown aria-hidden="true" className="text-ax-error size-4" />
                  {t("feedback_bad_answers")}
                </>
              }
              value={data.feedback.negative}
            />
          </dl>
        )}
      </QueryStateBoundary>

      <div className="border-ax-border rounded-ax-container flex flex-wrap items-center justify-between gap-3 border p-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{t("explore_conversations")}</p>
          <p className="text-ax-text-secondary text-sm">{t("view_all_conversations_users_had")}</p>
        </div>
        <Button
          label={t("explore_conversations")}
          variant="secondary"
          icon={<History className="size-4" aria-hidden="true" />}
          onClick={() => setExploring(true)}
        />
      </div>
      {exploring && (
        <ExploreConversationsDialog
          partner={partner}
          range={range}
          isOpen={exploring}
          onOpenChange={setExploring}
        />
      )}

      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const text = question.trim();
          if (ask.isPending) return;
          if (!text) {
            // An empty question shows at the field, which takes focus.
            flushSync(() => setAsked(true));
            questionRef.current?.focus();
            return;
          }
          setAnswer("");
          ask.mutate(text);
        }}
      >
        <TextArea
          ref={questionRef}
          label={t("ask_about_insights")}
          value={question}
          onChange={setQuestion}
          rows={3}
          status={questionProblem ? { type: "error", message: questionProblem } : undefined}
        />
        <Button
          type="submit"
          label={t("generate_insights")}
          variant="primary"
          icon={<SendHorizontal className="size-4" aria-hidden="true" />}
          // Stays focusable while the answer is prepared (a second submit is ignored).
          isLoading={ask.isPending}
          isInterruptible
          className="self-end"
        />
      </form>

      {ask.isPending ? (
        <LoadingState variant="text" rows={3} label={t("chat_insights_generating")} />
      ) : ask.isError ? (
        <ListError
          error={ask.error}
          onRetry={() => {
            if (ask.variables) ask.mutate(ask.variables);
          }}
        />
      ) : answer ? (
        <div className="bg-ax-sunken border-ax-border rounded-ax-container border p-4">
          <p className="text-sm font-medium">{t("answer")}</p>
          <div className="text-ax-text-secondary mt-2 text-sm whitespace-pre-wrap">{answer}</div>
        </div>
      ) : null}
    </div>
  );
}
