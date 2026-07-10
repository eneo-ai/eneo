export const load = async (event) => {
  event.depends("admin:web-search");

  const { eneo } = await event.parent();

  const [webSearchSettings, securityClassifications] = await Promise.all([
    eneo.mcpServers.listSettings({ purpose: "web_search" }),
    eneo.securityClassifications.list()
  ]);

  return {
    webSearchSettings,
    securityClassifications
  };
};
