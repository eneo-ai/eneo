"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
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
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 px-4 py-6">
      <div className="grid gap-3 sm:grid-cols-2">
        {stats.isPending ? (
          <>
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </>
        ) : stats.isError ? (
          <p className="text-destructive text-sm">{t("request_failed")}</p>
        ) : (
          <>
            <div className="rounded-lg border p-4">
              <p className="text-muted-foreground text-sm">{t("total_conversations")}</p>
              <p className="mt-1 text-3xl font-semibold tabular-nums">
                {stats.data.total_conversations}
              </p>
            </div>
            <div className="rounded-lg border p-4">
              <p className="text-muted-foreground text-sm">{t("total_questions")}</p>
              <p className="mt-1 text-3xl font-semibold tabular-nums">
                {stats.data.total_questions}
              </p>
            </div>
          </>
        )}
      </div>

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
        <Textarea
          value={question}
          rows={3}
          placeholder={t("ask_about_insights")}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <Button
          type="submit"
          className="w-fit self-end"
          disabled={!question.trim() || ask.isPending}
        >
          <SendHorizontal className="size-4" />
          {ask.isPending ? t("loading") : t("generate_insights")}
        </Button>
      </form>

      {(answer || ask.isError || ask.isPending) && (
        <div className="bg-muted/30 min-h-32 rounded-lg border p-4">
          <p className="text-sm font-medium">{t("answer")}</p>
          <div className="text-muted-foreground mt-2 text-sm whitespace-pre-wrap">
            {ask.isPending ? t("loading") : ask.isError ? t("request_failed") : answer}
          </div>
        </div>
      )}
    </div>
  );
}
