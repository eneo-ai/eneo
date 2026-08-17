// Copyright (c) 2026 Sundsvalls Kommun

import type { ChatMessage } from "./protocol";
import { getStructuredQuestionOptionKey } from "./structuredQuestionAnswer";

/** The answer to each question, as the user should read it back.
 *
 *  A typed answer usually arrives with the user's own words in the message.
 *  A delegated answer has no words — Eneo chose — so its label comes from the
 *  option the server named on the question it answered.
 */
export function buildAnswerLabels(messages: readonly ChatMessage[]): Map<string, string> {
  const questionOptionLabels = new Map<string, Map<string, string>>();
  for (const message of messages) {
    const question = message.question;
    if (!question) continue;
    const byKey = new Map<string, string>();
    for (const option of question.options) {
      byKey.set(getStructuredQuestionOptionKey(option), option.label);
      if (option.value != null) byKey.set(String(option.value), option.label);
    }
    questionOptionLabels.set(question.question_id, byKey);
  }

  const labels = new Map<string, string>();
  for (const message of messages) {
    const answer = message.questionAnswer;
    const questionId = answer?.question_id;
    if (!answer || !questionId) continue;

    const written = message.content.trim();
    if (written.length > 0) {
      labels.set(questionId, written);
      continue;
    }
    const optionLabels = questionOptionLabels.get(questionId);
    const named =
      answer.selected_option_id ??
      (answer.selected_value != null ? String(answer.selected_value) : null) ??
      answer.selected_option_ids?.[0] ??
      null;
    const label = named ? (optionLabels?.get(named) ?? named) : (answer.custom_value ?? null);
    if (label) labels.set(questionId, label);
  }
  return labels;
}
