export const load = async (event) => {
  const { intric } = await event.parent();
  const flowId = event.params.flowId;

  const flow = await intric.flows.get({ id: flowId });

  return { flow };
};
