import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";

/** The loopback server the flow chat's tools run on (the backend's `FLOWS_SERVER_NAME`). */
export const FLOWS_SERVER_NAME = "flows";

/** A call on Eneo's own flows server; an external server an admin named "flows" does not count. */
export function isFlowsToolCall(call: Pick<ToolCallRecord, "serverName" | "isInternal">): boolean {
  return call.serverName === FLOWS_SERVER_NAME && call.isInternal !== false;
}
