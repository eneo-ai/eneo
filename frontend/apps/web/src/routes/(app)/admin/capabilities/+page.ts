export const load = async (event) => {
  event.depends("admin:capabilities");

  const { eneo } = await event.parent();

  const [capabilitySettings, securityClassifications] = await Promise.all([
    eneo.mcpServers.listSettings(),
    eneo.securityClassifications.list()
  ]);

  return {
    capabilitySettings,
    securityClassifications
  };
};
