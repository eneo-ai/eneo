export const load = async (event) => {
  const { eneo } = await event.parent();

  const [mcpServers, mcpSettings, securityClassifications] = await Promise.all([
    eneo.mcpServers.list(),
    eneo.mcpServers.listSettings(),
    eneo.securityClassifications.list()
  ]);

  return {
    mcpServers,
    mcpSettings,
    securityClassifications
  };
};
