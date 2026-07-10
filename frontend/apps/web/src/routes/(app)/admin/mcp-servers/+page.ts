export const load = async (event) => {
  const { eneo } = await event.parent();

  // Web-search providers (purpose=web_search) are managed on the dedicated
  // web-search admin page, so this catalog only lists general-purpose servers.
  const [mcpServers, mcpSettings, securityClassifications] = await Promise.all([
    eneo.mcpServers.list({ purpose: "general" }),
    eneo.mcpServers.listSettings({ purpose: "general" }),
    eneo.securityClassifications.list()
  ]);

  return {
    mcpServers,
    mcpSettings,
    securityClassifications
  };
};
