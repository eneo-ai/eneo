export const load = async (event) => {
  const { intric } = await event.parent();

  const [mcpServers, mcpSettings, securityClassifications] = await Promise.all([
    intric.mcpServers.list(),
    intric.mcpServers.listSettings(),
    intric.securityClassifications.list()
  ]);

  return {
    mcpServers,
    mcpSettings,
    securityClassifications
  };
};
