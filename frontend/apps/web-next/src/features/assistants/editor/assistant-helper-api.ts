import { queryOptions } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { HelperChatApi } from "@/features/helper/helper-adapter";

export type AssistantHelperAvailability = Schema<"AssistantHelperChatAvailability">;

/**
 * Where the assistant's helper chat is cached. Outside `["assistants", id]`,
 * so refreshing the assistant after the chat's tools ran does not read the
 * chat or its availability again.
 */
export const assistantHelperKeys = {
  chat: (assistantId: string) => ["helper-chats", "assistant", assistantId] as const,
  availability: (assistantId: string) =>
    ["helper-chats", "availability", "assistant", assistantId] as const
};

/**
 * The assistant's helper chat endpoints. A mode change is not fenced (an
 * assistant has no revision); turning Redigera on after a pause may start a
 * new conversation, and the answer then names another `session_id`.
 */
export function assistantHelperApi(assistantId: string): HelperChatApi {
  const path = { id: assistantId };
  return {
    key: assistantHelperKeys.chat(assistantId),
    open: () =>
      unwrap(browserApi.POST("/api/v1/assistants/{id}/helper-chat/", { params: { path } })),
    update: (sessionId, body) =>
      unwrap(
        browserApi.PATCH("/api/v1/assistants/{id}/helper-chat/{session_id}/", {
          params: { path: { ...path, session_id: sessionId } },
          body
        })
      ),
    startConversation: (sessionId) =>
      unwrap(
        browserApi.POST("/api/v1/assistants/{id}/helper-chat/{session_id}/conversations/", {
          params: { path: { ...path, session_id: sessionId } }
        })
      )
  };
}

/** Whether the person can open the helper chat on the assistant, and why not. */
export function assistantHelperAvailabilityQueryOptions(api: EneoClient, assistantId: string) {
  return queryOptions({
    queryKey: assistantHelperKeys.availability(assistantId),
    queryFn: ({ signal }): Promise<AssistantHelperAvailability> =>
      unwrap(
        api.GET("/api/v1/assistants/{id}/helper-chat/availability", {
          params: { path: { id: assistantId } },
          signal
        })
      )
  });
}
