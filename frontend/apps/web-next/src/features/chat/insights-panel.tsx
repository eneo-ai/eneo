"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQuery } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";

type InsightPartner = Extract<ChatPartner["type"], "assistant" | "group-chat">;

const INSIGHT_DAYS = 30;
/** How long to wait for an asynchronous insight job, polled once a second. */
const MAX_POLLS = 120;

function partnerQuery(partner: ChatPartner): {
  assistant_id?: string;
  group_chat_id?: string;
} {
  if (partner.type === "assistant") return { assistant_id: partner.id };
  if (partner.type === "group-chat") return { group_chat_id: partner.id };
  return {};
}

function dateOnly(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function insightRange() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - INSIGHT_DAYS);
  return {
    startTime: start.toISOString(),
    endTime: end.toISOString(),
    fromDate: dateOnly(start),
    toDate: dateOnly(end)
  };
}

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

/**
 * Insikter for an assistant or group chat: the last 30 days' conversation and
 * question counts, and a question about those conversations. The answer is
 * announced when it is ready (it can take a while: the backend may run it as
 * a job); leaving the view stops waiting for it.
 */
export function InsightsPanel({ partner }: { partner: ChatPartner & { type: InsightPartner } }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const range = insightRange();
  const query = partnerQuery(partner);
  const request = useRef<AbortController | null>(null);

  // Stop polling a job when the view goes away.
  useEffect(() => () => request.current?.abort(), []);

  const stats = useQuery({
    queryKey: ["conversation-insights", "stats", partner.type, partner.id, range.fromDate],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/", {
          params: {
            query: {
              start_time: range.startTime,
              end_time: range.endTime,
              ...query
            }
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
              from_date: range.fromDate,
              to_date: range.toDate,
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
      {stats.isPending ? (
        <LoadingState rows={2} />
      ) : stats.isError ? (
        <p className="text-ax-error text-sm">{t("request_failed")}</p>
      ) : (
        <dl className="grid gap-3 sm:grid-cols-2">
          <div className="border-ax-border rounded-ax-container border p-4">
            <dt className="text-ax-text-secondary text-sm">{t("total_conversations")}</dt>
            <dd className="mt-1 text-3xl font-semibold tabular-nums">
              {stats.data.total_conversations}
            </dd>
          </div>
          <div className="border-ax-border rounded-ax-container border p-4">
            <dt className="text-ax-text-secondary text-sm">{t("total_questions")}</dt>
            <dd className="mt-1 text-3xl font-semibold tabular-nums">
              {stats.data.total_questions}
            </dd>
          </div>
        </dl>
      )}

      <form
        className="flex flex-col gap-2"
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
          value={question}
          onChange={setQuestion}
          rows={3}
        />
        <Button
          type="submit"
          label={t("generate_insights")}
          variant="primary"
          icon={<SendHorizontal className="size-4" aria-hidden="true" />}
          isDisabled={!question.trim()}
          // Stays focusable while the answer is prepared (a second submit is ignored).
          isLoading={ask.isPending}
          isInterruptible
          className="self-end"
        />
      </form>

      {ask.isPending ? (
        <LoadingState variant="text" rows={3} label={t("chat_insights_generating")} />
      ) : ask.isError ? (
        <p className="text-ax-error text-sm">{t("request_failed")}</p>
      ) : answer ? (
        <div className="bg-ax-sunken border-ax-border rounded-ax-container border p-4">
          <p className="text-sm font-medium">{t("answer")}</p>
          <div className="text-ax-text-secondary mt-2 text-sm whitespace-pre-wrap">{answer}</div>
        </div>
      ) : null}
    </div>
  );
}
