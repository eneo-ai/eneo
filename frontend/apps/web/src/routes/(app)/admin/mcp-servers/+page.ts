export const load = async (event) => {
  const { intric } = await event.parent();

  const [mcpServers, mcpSettings] = await Promise.all([
    intric.mcpServers.list(),
    intric.mcpServers.listSettings()
  ]);

  return {
    mcpServers,
    mcpSettings
  };
};
