"use client";

import { Card } from "@astryxdesign/core/Card";
import { useQuery } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { AssistantInsightFilters } from "./insights";

/**
 * How users rated an assistant's answers in the chosen time range: the count
 * of good and bad ratings, under the same filters as the question history.
 * Conversation-level feedback is not included.
 */
export function AnswerFeedbackSummary({
  assistantId,
  filters
}: {
  assistantId: string;
  filters: AssistantInsightFilters;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const counts = useQuery({
    queryKey: ["admin-insights-answer-feedback", assistantId, filters],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/assistants/{assistant_id}/feedback/", {
          params: {
            path: { assistant_id: assistantId },
            query: {
              from_date: filters.start,
              to_date: filters.end,
              include_followups: filters.includeFollowups
            }
          },
          signal
        })
      )
  });

  return (
    <Card className="flex flex-col gap-3">
      <p className="text-sm font-medium">{t("feedback_summary_title")}</p>
      {counts.isPending ? (
        <LoadingState rows={1} />
      ) : counts.isError ? (
        <p className="text-ax-error text-sm">{t("request_failed")}</p>
      ) : (
        <dl className="flex flex-wrap gap-x-8 gap-y-3">
          <div className="flex flex-col gap-1">
            <dt className="text-ax-text-secondary inline-flex items-center gap-1.5 text-sm">
              <ThumbsUp aria-hidden="true" className="text-ax-success size-4" />
              {t("feedback_good_answers")}
            </dt>
            <dd className="text-2xl font-semibold tabular-nums">
              {format.number(counts.data.positive)}
            </dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-ax-text-secondary inline-flex items-center gap-1.5 text-sm">
              <ThumbsDown aria-hidden="true" className="text-ax-error size-4" />
              {t("feedback_bad_answers")}
            </dt>
            <dd className="text-2xl font-semibold tabular-nums">
              {format.number(counts.data.negative)}
            </dd>
          </div>
        </dl>
      )}
    </Card>
  );
}
