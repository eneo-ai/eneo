export const load = async (event) => {
  const { intric } = await event.parent();
  const flowInputLimits = await intric.settings.getFlowInputLimits();
  return { flowInputLimits };
};
