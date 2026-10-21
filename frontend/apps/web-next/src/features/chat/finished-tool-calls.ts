import type { EneoUIMessage } from "@/lib/chat/types";
import { messageToolCalls, type ToolCallRecord } from "./side-panel/message-tool-calls";

/**
 * A call that has its result or its failure. The part's own state, not the
 * recorded `result_status`: a live call keeps "approved" there until the
 * conversation is read again.
 */
function isFinished(call: ToolCallRecord): boolean {
  return call.state === "output-available" || call.state === "output-error";
}

/** The ids of the conversation's finished tool calls. */
export function finishedToolCallIds(messages: readonly EneoUIMessage[]): string[] {
  return messages
    .flatMap(messageToolCalls)
    .filter(isFinished)
    .map((call) => call.toolCallId);
}

/**
 * The finished tool calls `seen` does not hold yet, in call order; they are
 * added to it, so each call is reported once however often the stream
 * re-renders the message.
 */
export function newlyFinishedToolCalls(
  messages: readonly EneoUIMessage[],
  seen: Set<string>
): ToolCallRecord[] {
  const fresh: ToolCallRecord[] = [];
  for (const call of messages.flatMap(messageToolCalls)) {
    if (!isFinished(call) || seen.has(call.toolCallId)) continue;
    seen.add(call.toolCallId);
    fresh.push(call);
  }
  return fresh;
}
