export const load = async (event) => {
  const { eneo } = await event.parent();

  // Every purpose is listed here: general servers and the capability
  // providers (web search, image generation), which are activated inline.
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
