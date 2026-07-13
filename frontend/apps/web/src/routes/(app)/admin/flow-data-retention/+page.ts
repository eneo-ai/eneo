export const load = async (event) => {
  const { eneo } = await event.parent();
  return { flowRetentionPolicy: await eneo.settings.getFlowRetentionPolicy() };
};
