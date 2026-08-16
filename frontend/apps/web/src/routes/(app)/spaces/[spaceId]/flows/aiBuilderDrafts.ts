import type { Eneo } from "@eneo/eneo-js";
import { hasPermission } from "$lib/core/hasPermission";
import {
  isRecoverableCreateDraft,
  type AIBuilderSessionListResponse,
  type RecoverableAIBuilderDraftSession
} from "$lib/features/flows/ai-builder/protocol";

interface LoadArgs {
  eneo: Pick<Eneo, "client">;
  currentSpace: { id: string };
  user: Parameters<typeof hasPermission>[0];
}

export type AIBuilderDraftsLoad =
  | { status: "loaded"; drafts: RecoverableAIBuilderDraftSession[] }
  | { status: "hidden" }
  | { status: "unavailable" };

/** In-progress AI drafts are rows in the Flöden list, so the page cannot
 *  silently pretend there are none: a failed request is reported as
 *  `unavailable` and the list says so. Users without builder access simply
 *  never see draft rows. */
export async function loadAIBuilderDrafts({
  eneo,
  currentSpace,
  user
}: LoadArgs): Promise<AIBuilderDraftsLoad> {
  if (!hasPermission(user)({ allOf: ["flows_manage", "flows_ai_builder"] })) {
    return { status: "hidden" };
  }
  try {
    // Assignment (not a cast) so schema drift on the endpoint fails the build.
    // The server owns the draft definition; the client filter only narrows types.
    const result: AIBuilderSessionListResponse = await eneo.client.fetch(
      "/api/v1/flows/ai-builder/sessions",
      {
        method: "get",
        params: {
          query: {
            space_id: currentSpace.id,
            target_kind: "create",
            drafts_only: true,
            limit: 100
          }
        }
      }
    );
    return {
      status: "loaded",
      drafts: result.sessions.filter((session) =>
        isRecoverableCreateDraft(session, currentSpace.id)
      )
    };
  } catch {
    return { status: "unavailable" };
  }
}

/** Discarding a draft cancels its builder session; the row disappears. */
export async function discardAIBuilderDraft(
  eneo: Pick<Eneo, "client">,
  sessionId: string
): Promise<void> {
  await eneo.client.fetch("/api/v1/flows/ai-builder/sessions/{session_id}/cancel", {
    method: "post",
    params: { path: { session_id: sessionId } }
  });
}
