import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  event.depends("admin:tools");
  event.depends("admin:models:load");
  event.depends("admin:model-providers:load");
  const { eneo } = await event.parent();
  const [mcpSettings, securityClassifications, providers] = await Promise.all([
    eneo.mcpServers.listSettings(),
    eneo.securityClassifications.list(),
    eneo.modelProviders.list()
  ]);
  return { mcpSettings, securityClassifications, providers };
};
