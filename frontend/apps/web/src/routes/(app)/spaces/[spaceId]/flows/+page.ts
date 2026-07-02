import { error } from "@sveltejs/kit";
import { hasPermission } from "$lib/core/hasPermission";

export const load = async (event) => {
  const { eneo, currentSpace, user } = await event.parent();

  const isOrgSpace = currentSpace.organization === true;
  if (isOrgSpace) {
    throw error(404);
  }

  if (!hasPermission(user)("flows_view")) {
    throw error(403);
  }

  const flowsData = await eneo.flows.list({ spaceId: currentSpace.id });
  const flows = flowsData.items ?? flowsData;

  return { flows };
};
