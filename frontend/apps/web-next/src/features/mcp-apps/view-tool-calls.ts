import type { QueryClient } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { ToolCallOutcome } from "./bridge";

/**
 * Calls a tool on the view's own server, for the user. The result is returned
 * to the view and is not added to the conversation.
 */
export function callToolFromView(params: {
  sessionId: string;
  toolCallId: string;
  viewId: string;
  name: string;
  arguments: Record<string, unknown>;
}): Promise<Schema<"ViewToolCallResultPublic">> {
  return unwrap(
    browserApi.POST("/api/v1/conversations/{session_id}/tool-calls/{tool_call_id}/app-calls/", {
      params: { path: { session_id: params.sessionId, tool_call_id: params.toolCallId } },
      body: { view_id: params.viewId, name: params.name, arguments: params.arguments }
    })
  );
}

/**
 * A finished call's stored result, fetched once per conversation and call: a
 * result never changes, so the same promise serves every view of it.
 */
export function toolCallOutcome(
  queryClient: QueryClient,
  sessionId: string,
  toolCallId: string
): Promise<ToolCallOutcome | null> {
  return queryClient.query({
    queryKey: ["conversations", "tool-call-outcome", sessionId, toolCallId],
    staleTime: Infinity,
    queryFn: async () => {
      const result = await unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/tool-calls/{tool_call_id}/result/", {
          params: { path: { session_id: sessionId, tool_call_id: toolCallId } }
        })
      );
      return {
        result: result.result ?? null,
        structuredContent: result.structured_content ?? null,
        isError: result.is_error ?? false
      } satisfies ToolCallOutcome;
    }
  });
}
