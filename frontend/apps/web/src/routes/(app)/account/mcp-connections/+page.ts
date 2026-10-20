export const load = async (event) => {
  const { eneo } = await event.parent();

  const connections = await eneo.mcpOauth.myConnections();

  return { connections };
};
