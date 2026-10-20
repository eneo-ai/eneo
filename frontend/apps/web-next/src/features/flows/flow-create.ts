import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { FlowPublic } from "./types";

/**
 * Creates an empty draft in a space. The flow exists before its chat does:
 * the authoring assistant only ever edits the flow its chat is bound to.
 */
export function createFlow(spaceId: string, name: string): Promise<FlowPublic> {
  return unwrap(browserApi.POST("/api/v1/flows/", { body: { space_id: spaceId, name } }));
}

/** Binds the chat that just started to the flow, so a reload reopens it. */
export function bindFlowConversation(flowId: string, sessionId: string): Promise<unknown> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/conversation/", {
      params: { path: { id: flowId } },
      body: { session_id: sessionId }
    })
  );
}
