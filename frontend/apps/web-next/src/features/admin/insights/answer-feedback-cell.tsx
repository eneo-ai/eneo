"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import type { Schema } from "@/lib/api/models";

/**
 * How the conversation's owner rated an answer, for a row of the question
 * history: the thumb with its name, and the comment when there is one. Who
 * rated is never shown; insights show no users.
 */
export function AnswerFeedbackCell({ feedback }: { feedback?: Schema<"MessageFeedback"> | null }) {
  const t = useTranslations();

  if (!feedback) {
    return (
      <span className="text-ax-text-secondary">
        <span aria-hidden="true">–</span>
        <span className="sr-only">{t("feedback_none")}</span>
      </span>
    );
  }

  const good = feedback.value === 1;
  const Icon = good ? ThumbsUp : ThumbsDown;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="inline-flex items-center gap-1.5 font-medium">
        <Icon
          aria-hidden="true"
          className={good ? "text-ax-success size-4 shrink-0" : "text-ax-error size-4 shrink-0"}
        />
        {good ? t("chat_feedback_good") : t("chat_feedback_bad")}
      </span>
      {feedback.text && (
        <p className="text-ax-text-secondary text-sm break-words whitespace-pre-wrap">
          <span className="sr-only">{t("feedback_comment")}: </span>
          {feedback.text}
        </p>
      )}
    </div>
  );
}
