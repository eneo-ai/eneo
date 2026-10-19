"use client";

import type { EneoUIMessage } from "@/lib/chat/types";
import { McpAppFrame } from "./mcp-app-frame";
import { messageAppViewCalls } from "./mcp-apps";

/**
 * The interactive views of an answer: HTML an approved tool brings, shown in
 * a sandboxed frame under the answer. A view belongs to one tool call and is
 * there from the moment the model starts writing the call.
 */
export function McpAppFrames({
  message,
  live,
  sessionId
}: {
  message: EneoUIMessage;
  /** The answer is being written right now. */
  live: boolean;
  sessionId: string | null;
}) {
  const calls = messageAppViewCalls(message);
  if (calls.length === 0) return null;
  return (
    <>
      {calls.map((call) => (
        <McpAppFrame key={call.toolCallId} call={call} live={live} sessionId={sessionId} />
      ))}
    </>
  );
}
