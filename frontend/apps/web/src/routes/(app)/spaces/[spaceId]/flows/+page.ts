import { error } from "@sveltejs/kit";
import { hasPermission } from "$lib/core/hasPermission";
import { loadAIBuilderDrafts } from "./aiBuilderDrafts";
import type { Eneo } from "@eneo/eneo-js";
import { FlowListPaginationError, loadFlowList } from "$lib/features/flows/flowListLoader";
import { m } from "$lib/paraglide/messages";

export const load = async (event: {
  parent: () => Promise<{
    eneo: Eneo;
    currentSpace: { id: string; organization?: boolean };
    user: Parameters<typeof hasPermission>[0];
  }>;
}) => {
  const { eneo, currentSpace, user } = await event.parent();

  const isOrgSpace = currentSpace.organization === true;
  if (isOrgSpace) {
    throw error(404);
  }

  if (!hasPermission(user)("flows_view")) {
    throw error(403);
  }

  const [flows, aiDrafts] = await Promise.all([
    loadFlowList(eneo, currentSpace.id).catch((cause: unknown) => {
      if (cause instanceof FlowListPaginationError) {
        throw error(502, { status: 502, code: 0, message: m.flow_list_load_failed() });
      }
      throw cause;
    }),
    loadAIBuilderDrafts({ eneo, currentSpace, user })
  ]);
  return { flows, aiDrafts };
};
