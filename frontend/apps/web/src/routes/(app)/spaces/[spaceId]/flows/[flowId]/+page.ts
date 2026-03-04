import { error } from "@sveltejs/kit";

export const load = async (event) => {
  const { intric, currentSpace } = await event.parent();
  const flowId = event.params.flowId;

  const flow = await intric.flows.get({ id: flowId });
  if (flow.space_id !== currentSpace.id) {
    throw error(404);
  }

  return { flow };
};
