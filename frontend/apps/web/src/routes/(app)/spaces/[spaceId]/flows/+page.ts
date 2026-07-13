import { error } from "@sveltejs/kit";
import { hasPermission } from "$lib/core/hasPermission";
import {
  isRecoverableCreateDraft,
  type AIBuilderDraftSession,
  type RecoverableAIBuilderDraftSession
} from "$lib/features/flows/ai-builder/protocol";

export const load = async (event) => {
  const { eneo, currentSpace, user } = await event.parent();

  const isOrgSpace = currentSpace.organization === true;
  if (isOrgSpace) {
    throw error(404);
  }

  if (!hasPermission(user)("flows_view")) {
    throw error(403);
  }

  // In-progress AI-builder drafts are only reachable through the builder page,
  // so the list page surfaces a resume strip for users who can open it. The
  // fetch is tolerant: without it the page just lacks the strip.
  const loadAiDrafts = async (): Promise<RecoverableAIBuilderDraftSession[]> => {
    if (!hasPermission(user)({ allOf: ["flows_manage", "flows_ai_builder"] })) {
      return [];
    }
    try {
      const result = (await eneo.client.fetch("/api/v1/flows/ai-builder/sessions", {
        method: "get"
      })) as { sessions?: AIBuilderDraftSession[] };
      return (result.sessions ?? []).filter((session) =>
        isRecoverableCreateDraft(session, currentSpace.id)
      );
    } catch {
      return [];
    }
  };

  const [flowsData, aiDrafts] = await Promise.all([
    eneo.flows.list({ spaceId: currentSpace.id }),
    loadAiDrafts()
  ]);
  const flows = flowsData.items ?? flowsData;

  return { flows, aiDrafts };
};
