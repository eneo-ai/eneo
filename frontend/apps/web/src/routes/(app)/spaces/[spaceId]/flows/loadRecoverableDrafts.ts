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
 *  missing permissions, failure, or timeout the page simply lacks the strip. */
export async function loadRecoverableDrafts({
  eneo,
  currentSpace,
  user
}: LoadArgs): Promise<RecoverableAIBuilderDraftSession[]> {
  if (!hasPermission(user)({ allOf: ["flows_manage", "flows_ai_builder"] })) {
    return [];
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  const budget = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), AI_DRAFTS_TIMEOUT_MS);
  });
  try {
    const result = await Promise.race([
      eneo.client.fetch("/api/v1/flows/ai-builder/sessions", {
        method: "get"
      }) as Promise<AIBuilderSessionListResponse>,
      budget
    ]);
    if (result === null) return [];
    return result.sessions.filter((session) => isRecoverableCreateDraft(session, currentSpace.id));
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}
