import { useMutation, useQueryClient } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { useSpace } from "@/features/spaces/use-space";
import { appQueryOptions } from "../apps";

export type AppUpdate = Schema<"AppUpdateRequest">;

export { appQueryOptions };

/**
 * Partial app update (PATCH /api/v1/apps/{id}/ leaves omitted fields
 * unchanged). Refreshes both the app and the space list.
 */
export function useUpdateApp(appId: string, onSuccess?: () => void) {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();

  // Feedback is owned by the caller's autosave wrapper (useAutosave); this
  // mutation only refreshes the cache.
  return useMutation({
    scope: { id: `app:${appId}` },
    mutationFn: (body: AppUpdate) =>
      unwrap(browserApi.PATCH("/api/v1/apps/{id}/", { params: { path: { id: appId } }, body })),
    onSuccess: (app) => {
      queryClient.setQueryData(appQueryOptions(browserApi, appId).queryKey, app);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      onSuccess?.();
    }
  });
}
