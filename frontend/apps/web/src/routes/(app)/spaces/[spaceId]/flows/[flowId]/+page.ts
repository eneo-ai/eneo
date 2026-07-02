import { error } from "@sveltejs/kit";
import { hasPermission } from "$lib/core/hasPermission";

export const ssr = false;

export const load = async (event) => {
  const { eneo, currentSpace, user } = await event.parent();
  const flowId = event.params.flowId;

  if (!hasPermission(user)("flows_manage")) {
    throw error(403);
  }

  const flow = await eneo.flows.get({ id: flowId });
  if (flow.space_id !== currentSpace.id) {
    throw error(404);
  }

  return { flow };
};
