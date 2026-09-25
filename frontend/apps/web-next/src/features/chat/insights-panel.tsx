"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";

type InsightPartner = Extract<ChatPartner["type"], "assistant" | "group-chat">;

const INSIGHT_DAYS = 30;

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

async function resolveInsightAnswer(response: unknown): Promise<string> {
  const immediate = stringField(response, "answer");
  if (immediate && !booleanField(response, "is_async")) return immediate;

  const jobId = stringField(response, "job_id") ?? stringField(response, "jobId");
  if (!jobId) return immediate ?? "";

  for (let attempt = 0; attempt < 120; attempt += 1) {
    const status = await unwrap(
      browserApi.GET("/api/v1/analysis/conversation-insights/jobs/{job_id}/", {
        params: { path: { job_id: jobId } }
      })
    );
    if (status.status === "completed") return status.answer ?? "";
    if (status.status === "failed") throw new Error(status.error ?? "Failed");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  throw new Error("Timed out");
}

export function InsightsPanel({ partner }: { partner: ChatPartner & { type: InsightPartner } }) {
  const t = useTranslations();
  const questionId = useId();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const range = insightRange();
  const query = partnerQuery(partner);

  const stats = useQuery({
    queryKey: ["conversation-insights", "stats", partner.type, partner.id, range.fromDate],
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/", {
          params: {
            query: {
              start_time: range.startTime,
              end_time: range.endTime,
              ...query
            }
          }
        })
      )
  });

  const ask = useMutation({
    mutationFn: async (text: string) => {
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
          body: { question: text }
        })
      );
      return resolveInsightAnswer(response);
    },
    onSuccess: setAnswer
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
        <Label htmlFor={questionId}>{t("ask_about_insights")}</Label>
        <Textarea
          id={questionId}
          value={question}
          rows={3}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <Button
          type="submit"
          className="w-fit self-end"
          disabled={!question.trim() || ask.isPending}
        >
          <SendHorizontal className="size-4" aria-hidden="true" />
          {ask.isPending ? t("loading") : t("generate_insights")}
        </Button>
      </form>

      {/* Always mounted so the finished answer is announced politely. */}
      <div role="status" className="flex flex-col">
        {(answer || ask.isError || ask.isPending) && (
          <div className="bg-ax-sunken border-ax-border rounded-ax-container min-h-32 border p-4">
            <p className="text-sm font-medium">{t("answer")}</p>
            <div className="text-ax-text-secondary mt-2 text-sm whitespace-pre-wrap">
              {ask.isPending ? t("loading") : ask.isError ? t("request_failed") : answer}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
