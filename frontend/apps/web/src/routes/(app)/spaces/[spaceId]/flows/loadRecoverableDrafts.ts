import type { Eneo } from "@eneo/eneo-js";
import { hasPermission } from "$lib/core/hasPermission";
import {
  isRecoverableCreateDraft,
  type AIBuilderSessionListResponse,
  type RecoverableAIBuilderDraftSession
} from "$lib/features/flows/ai-builder/protocol";

/** The drafts strip is an optional enhancement: it may never delay the flows
 *  list itself, so its request gets this hard budget and then loses its slot. */
export const AI_DRAFTS_TIMEOUT_MS = 800;

interface LoadArgs {
  eneo: Pick<Eneo, "client">;
  currentSpace: { id: string };
  user: Parameters<typeof hasPermission>[0];
}

/** Recoverable create drafts for the resume strip. Tolerant by design: on
 *  missing permissions, failure, or timeout the page simply lacks the strip.
 *  The deadline ABORTS the request — a degraded backend must not keep an
 *  abandoned connection open per flows-page visit. */
export async function loadRecoverableDrafts({
  eneo,
  currentSpace,
  user
}: LoadArgs): Promise<RecoverableAIBuilderDraftSession[]> {
  if (!hasPermission(user)({ allOf: ["flows_manage", "flows_ai_builder"] })) {
    return [];
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), AI_DRAFTS_TIMEOUT_MS);
  try {
    // Assignment (not a cast) so schema drift on the endpoint fails the build.
    const result: AIBuilderSessionListResponse = await eneo.client.fetch(
      "/api/v1/flows/ai-builder/sessions",
      { method: "get", signal: controller.signal }
    );
    return result.sessions.filter((session) => isRecoverableCreateDraft(session, currentSpace.id));
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}
