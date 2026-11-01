import type { EneoUIMessage } from "@/lib/chat/types";
import { messageToolCalls, type ToolCallRecord } from "./side-panel/message-tool-calls";

/** The built-in server a question to the person is a step on, and its one tool. */
export const QUESTIONS_SERVER = "questions";
export const ASK_USER_TOOL = "ask_user";

export type QuestionOption = { label: string; description: string | null };

/** A question the assistant asked, as the backend put it on the call. */
export type AskedQuestion = {
  question: string;
  header: string | null;
  options: QuestionOption[];
  multiSelect: boolean;
};

/** A question waiting for the person's answer, and the call that asked it. */
export type OpenQuestion = AskedQuestion & { messageId: string; toolCallId: string };

/** Whether a call is a question to the person (on Eneo's own `questions` server). */
export function isQuestionCall(
  call: Pick<ToolCallRecord, "serverName" | "toolName" | "isInternal">
): boolean {
  return (
    call.serverName === QUESTIONS_SERVER &&
    call.isInternal !== false &&
    call.toolName === ASK_USER_TOOL
  );
}

const asText = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;

/** The question a call asked, from its structured content; null for any other call or a refused one. */
export function questionOf(call: ToolCallRecord): AskedQuestion | null {
  if (!isQuestionCall(call) || call.resultStatus !== "succeeded") return null;
  const content = call.structuredContent;
  const question = asText(content?.question);
  if (!question || !Array.isArray(content?.options)) return null;
  const options: QuestionOption[] = [];
  for (const option of content.options as unknown[]) {
    if (!option || typeof option !== "object") continue;
    const label = asText((option as { label?: unknown }).label);
    if (!label) continue;
    options.push({
      label,
      description: asText((option as { description?: unknown }).description)
    });
  }
  if (options.length < 2) return null;
  return {
    question,
    header: asText(content?.header),
    options,
    multiSelect: content?.multi_select === true
  };
}

/** The question an answer ends with, when it does. */
function questionAskedBy(message: EneoUIMessage): OpenQuestion | null {
  if (message.role !== "assistant") return null;
  for (const call of messageToolCalls(message).reverse()) {
    const question = questionOf(call);
    if (question) return { ...question, messageId: message.id, toolCallId: call.toolCallId };
  }
  return null;
}

/**
 * The question the person has not answered yet: the one the last answer
 * ends with, once the answer is complete. A message sent after it (any
 * message: the pick, or free text) is the answer, so it is open no more.
 */
export function questionToAnswer(messages: EneoUIMessage[], busy: boolean): OpenQuestion | null {
  if (busy) return null;
  const last = messages.at(-1);
  return last ? questionAskedBy(last) : null;
}

/** The question the message at `index` answers: the one the answer before it ends with. */
export function questionAnsweredBy(messages: EneoUIMessage[], index: number): AskedQuestion | null {
  const message = messages[index];
  const before = messages[index - 1];
  if (!message || message.role !== "user" || !before) return null;
  return questionAskedBy(before);
}

/**
 * The message an answer is sent as: the picked labels, in the question's
 * order, and the person's own words after them. Empty when nothing was
 * picked or written.
 */
export function questionAnswer(
  question: AskedQuestion,
  picked: readonly string[],
  other: string
): string {
  const labels = question.options
    .map((option) => option.label)
    .filter((label) => picked.includes(label));
  const own = other.trim();
  if (labels.length === 0) return own;
  return own ? `${labels.join(", ")}. ${own}` : labels.join(", ");
}
