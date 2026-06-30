import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { useSpace } from "@/features/spaces/use-space";

export type Assistant = Schema<"AssistantPublic">;
export type AssistantUpdate = Schema<"PartialAssistantUpdatePublic">;

export function assistantQueryOptions(api: EneoClient, assistantId: string) {
  return queryOptions({
    queryKey: ["assistants", assistantId],
    queryFn: (): Promise<Assistant> =>
      unwrap(api.GET("/api/v1/assistants/{id}/", { params: { path: { id: assistantId } } }))
  });
}

/**
 * Partial assistant update (the backend leaves omitted fields unchanged;
 * POST-as-update is RB-5(b)). Refreshes both the assistant and the space.
 */
export function useUpdateAssistant(assistantId: string, onSuccess?: () => void) {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();

  // Error/success feedback is owned by the caller's autosave wrapper
  // (useAutosave), so this mutation only updates the cache.
  return useMutation({
    mutationFn: (body: AssistantUpdate) =>
      unwrap(
        browserApi.POST("/api/v1/assistants/{id}/", {
          params: { path: { id: assistantId } },
          body
        })
      ),
    onSuccess: (assistant) => {
      queryClient.setQueryData(assistantQueryOptions(browserApi, assistantId).queryKey, assistant);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      onSuccess?.();
    }
  });
}
