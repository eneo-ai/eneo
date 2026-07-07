import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { useSpace } from "@/features/spaces/use-space";

export type GroupChat = Schema<"GroupChatPublic">;
export type GroupChatUpdate = Schema<"GroupChatUpdateSchema">;
export type GroupChatAssistant = Schema<"GroupChatAssistantPublic">;

/** Same key the chat page uses for the partner, so edits refresh it too. */
export function groupChatQueryOptions(api: EneoClient, groupChatId: string) {
  return queryOptions({
    queryKey: ["group-chats", groupChatId],
    queryFn: (): Promise<GroupChat> =>
      unwrap(api.GET("/api/v1/group-chats/{id}/", { params: { path: { id: groupChatId } } }))
  });
}

export function useUpdateGroupChat(groupChatId: string) {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();

  // Feedback is owned by the caller's autosave wrapper (useAutosave); this
  // mutation only refreshes the cache.
  return useMutation({
    scope: { id: `group-chat:${groupChatId}` },
    mutationFn: (body: GroupChatUpdate) =>
      unwrap(
        browserApi.PATCH("/api/v1/group-chats/{id}/", {
          params: { path: { id: groupChatId } },
          body
        })
      ),
    onSuccess: (groupChat) => {
      queryClient.setQueryData(groupChatQueryOptions(browserApi, groupChatId).queryKey, groupChat);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
    }
  });
}
