import { queryOptions, type QueryClient } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { hasPermission } from "@/lib/auth/permissions";

export type FlowPublic = Schema<"FlowPublic">;
export type FlowSparse = Schema<"FlowSparsePublic">;
export type FlowStep = Schema<"FlowStepPublic">;
export type FlowEditorUpdate = Schema<"FlowEditorUpdateRequest">;
export type FlowStepSlot = Schema<"FlowEditorStepSlot">;
export type FlowDefinitionUpdate = Schema<"PartialFlowUpdateRequest">;
export type FlowAuthoringChat = Schema<"FlowAuthoringChatPublic">;

/**
 * Query keys. A flow's own key (`flow`) is what everything that changes the
 * draft refreshes: the editor, publication and the chat's tools.
 */
export const flowKeys = {
  lists: ["flows", "list"] as const,
  list: (spaceId: string) => ["flows", "list", spaceId] as const,
  flow: (flowId: string) => ["flows", "detail", flowId] as const,
  authoringChat: (flowId: string) => ["flows", "authoring-chat", flowId] as const
};

/** Flows per request when a space's list is read; the list reads every page. */
const LIST_PAGE_SIZE = 100;
/** A space with more flows than this many pages is cut off rather than read forever. */
const LIST_MAX_PAGES = 20;

/** Every flow of a space (drafts only where the caller may edit), oldest first. */
export async function listSpaceFlows(api: EneoClient, spaceId: string): Promise<FlowSparse[]> {
  const flows: FlowSparse[] = [];
  for (let page = 0; page < LIST_MAX_PAGES; page += 1) {
    const result = await unwrap(
      api.GET("/api/v1/flows/", {
        params: {
          query: { space_id: spaceId, limit: LIST_PAGE_SIZE, offset: page * LIST_PAGE_SIZE }
        }
      })
    );
    flows.push(...result.items);
    if (!result.has_more) break;
  }
  return flows;
}

export function flowsListQueryOptions(api: EneoClient, spaceId: string) {
  return queryOptions({
    queryKey: flowKeys.list(spaceId),
    queryFn: () => listSpaceFlows(api, spaceId)
  });
}

export function flowQueryOptions(api: EneoClient, flowId: string) {
  return queryOptions({
    queryKey: flowKeys.flow(flowId),
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/v1/flows/{id}/", { params: { path: { id: flowId } }, signal }))
  });
}

/**
 * Whether flows are shown to this user: the tenant has them switched on
 * (`flows_enabled` in the settings, the `flows_core` gate that answers 404 on
 * every flow route when off) and the user may see flows (`flows_view`).
 */
export function flowsAvailable(
  settings: Pick<Schema<"SettingsPublic">, "flows_enabled">,
  user: Parameters<typeof hasPermission>[0]
): boolean {
  return settings.flows_enabled === true && hasPermission(user)("flows_view");
}

export function createFlow(body: {
  spaceId: string;
  name: string;
  description: string | null;
}): Promise<FlowPublic> {
  return unwrap(
    browserApi.POST("/api/v1/flows/", {
      body: {
        space_id: body.spaceId,
        name: body.name,
        description: body.description
      }
    })
  );
}

export function deleteFlow(flowId: string): Promise<unknown> {
  return unwrap(browserApi.DELETE("/api/v1/flows/{id}/", { params: { path: { id: flowId } } }));
}

/**
 * One revision-fenced edit through the editor endpoint: settings, step edits,
 * new steps and the step order save together or not at all.
 */
export function updateFlowEditor(flowId: string, body: FlowEditorUpdate): Promise<FlowPublic> {
  return unwrap(
    browserApi.PATCH("/api/v1/flows/{id}/editor/", { params: { path: { id: flowId } }, body })
  );
}

/** Publishes the draft the caller has seen (`expected_revision`), never a newer one. */
export function publishFlow(flow: Pick<FlowPublic, "id" | "draft_revision">): Promise<FlowPublic> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/publish/", {
      params: { path: { id: flow.id }, query: { expected_revision: flow.draft_revision } }
    })
  );
}

export function unpublishFlow(
  flow: Pick<FlowPublic, "id" | "draft_revision">
): Promise<FlowPublic> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/unpublish/", {
      params: { path: { id: flow.id }, query: { expected_revision: flow.draft_revision } }
    })
  );
}

/**
 * The caller's chat for the flow, created on first use (one per user and
 * flow). It is a POST, so it is read once per visit and not refetched in the
 * background.
 */
export function authoringChatQueryOptions(flowId: string) {
  return queryOptions({
    queryKey: flowKeys.authoringChat(flowId),
    queryFn: () =>
      unwrap(
        browserApi.POST("/api/v1/flows/{id}/authoring-chat/", { params: { path: { id: flowId } } })
      ),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false
  });
}

/**
 * Turns the chat's edit mode on or off, fenced on the draft revision the
 * caller has seen. Turning it on after a pause may start a new conversation:
 * the answer then names another `session_id`.
 */
export function setAuthoringMode(
  chat: Pick<FlowAuthoringChat, "flow_id" | "session_id">,
  body: { editing: boolean; expectedRevision: number }
): Promise<FlowAuthoringChat> {
  return updateAuthoringChat(chat, {
    editing: body.editing,
    expected_revision: body.expectedRevision
  });
}

/**
 * Changes the chat's edit mode, model or reasoning effort; a null model or
 * effort returns to the default.
 */
export function updateAuthoringChat(
  chat: Pick<FlowAuthoringChat, "flow_id" | "session_id">,
  body: Schema<"FlowAuthoringChatUpdateRequest">
): Promise<FlowAuthoringChat> {
  return unwrap(
    browserApi.PATCH("/api/v1/flows/{id}/authoring-chat/{session_id}/", {
      params: { path: { id: chat.flow_id, session_id: chat.session_id } },
      body
    })
  );
}

/** Leaves the chat's conversation for a new, empty one with the same assistant. */
export function startAuthoringConversation(
  chat: Pick<FlowAuthoringChat, "flow_id" | "session_id">
): Promise<FlowAuthoringChat> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/authoring-chat/{session_id}/conversations/", {
      params: { path: { id: chat.flow_id, session_id: chat.session_id } }
    })
  );
}

/** Puts a flow the server returned into the cache and marks the space's list stale. */
export function storeFlow(queryClient: QueryClient, flow: FlowPublic): void {
  queryClient.setQueryData(flowKeys.flow(flow.id), flow);
  void queryClient.invalidateQueries({ queryKey: flowKeys.list(flow.space_id) });
}

/** The backend's refusal code (`code` on the error body), when there is one. */
export function refusalCode(error: unknown): string | null {
  return error instanceof EneoApiError ? (error.reason ?? null) : null;
}
