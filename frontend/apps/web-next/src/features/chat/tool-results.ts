import { createContext } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";

/**
 * Where a finished tool call's result is read: the stream carries a call's
 * status, never its result, so a row of the Steg tab asks for it when it
 * opens. A conversation on other endpoints than the chat API (the insights
 * chat) reads them from its own.
 */
export type ToolResultSource = {
  /** First part of the results' query keys, so two sources never share a cached result. */
  scope: string;
  read: (sessionId: string, toolCallId: string) => Promise<string | null>;
};

/** The chat API's results. */
export const conversationToolResults: ToolResultSource = {
  scope: "conversations",
  read: async (sessionId, toolCallId) => {
    const response = await unwrap(
      browserApi.GET("/api/v1/conversations/{session_id}/tool-calls/{tool_call_id}/result/", {
        params: { path: { session_id: sessionId, tool_call_id: toolCallId } }
      })
    );
    return response.result ?? null;
  }
};

export const ToolResultsContext = createContext<ToolResultSource>(conversationToolResults);
