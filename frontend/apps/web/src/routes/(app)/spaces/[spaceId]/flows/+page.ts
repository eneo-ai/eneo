import { error } from "@sveltejs/kit";
import { hasPermission } from "$lib/core/hasPermission";
import { loadRecoverableDrafts } from "./loadRecoverableDrafts";

export const load = async (event) => {
  const { eneo, currentSpace, user } = await event.parent();

  const isOrgSpace = currentSpace.organization === true;
  if (isOrgSpace) {
    throw error(404);
  }

  if (!hasPermission(user)("flows_view")) {
    throw error(403);
  }

  const [flowsData, aiDrafts] = await Promise.all([
    eneo.flows.list({ spaceId: currentSpace.id }),
    loadRecoverableDrafts({ eneo, currentSpace, user })
  ]);
  const flows = flowsData.items ?? flowsData;

  return { flows, aiDrafts };
};
