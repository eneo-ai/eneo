"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { AnswerRating } from "@/lib/chat/types";

const FEEDBACK_PATH = "/api/v1/conversations/{session_id}/messages/{message_id}/feedback/";

type Save = { sessionId: string; value: AnswerRating };

/**
 * The rating of one saved answer, saved on each change (a rating replaces the
 * earlier one; none clears it). Shows the latest press at once and keeps the
 * control enabled: presses are saved one after another, so a press during a
 * save is sent when that save finishes. A failed save shows an error and falls
 * back to the last saved rating; a saved change is announced.
 */
export function useAnswerFeedback(
  messageId: string,
  /** The rating stored with the answer when it was loaded. */
  initial: AnswerRating
): [AnswerRating, (sessionId: string, value: AnswerRating) => void] {
  const t = useTranslations();
  const announce = useAnnounce();
  const [saved, setSaved] = useState(initial);
  const mutation = useMutation({
    mutationFn: async ({ sessionId, value }: Save) => {
      const params = { path: { session_id: sessionId, message_id: messageId } };
      if (value === null) await unwrap(browserApi.DELETE(FEEDBACK_PATH, { params }));
      else await unwrap(browserApi.PUT(FEEDBACK_PATH, { params, body: { value } }));
    },
    scope: { id: `answer-feedback:${messageId}` },
    onSuccess: (_data, { value }) => {
      setSaved(value);
      announce(t(value === null ? "feedback_removed" : "chat_feedback_thanks"));
    },
    onError: (error) => toastApiError(error, t)
  });

  return [
    mutation.isPending ? mutation.variables.value : saved,
    (sessionId, value) => mutation.mutate({ sessionId, value })
  ];
}
