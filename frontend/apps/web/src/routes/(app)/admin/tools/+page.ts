import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  event.depends("admin:tools");
  event.depends("admin:models:load");
  event.depends("admin:model-providers:load");
  const { eneo } = await event.parent();
  const [mcpSettings, securityClassifications, providers, bundled, documentTemplates] =
    await Promise.all([
      eneo.mcpServers.listSettings(),
      eneo.securityClassifications.list(),
      eneo.modelProviders.list(),
      // Optional: an older backend without the bundled runtime lists nothing.
      eneo.mcpServers.listBundled().catch(() => ({ items: [], count: 0 })),
      // Optional: an older backend has no document templates (null, not an empty library).
      eneo.documentTemplates.list().catch(() => null)
    ]);
  return { mcpSettings, securityClassifications, providers, bundled, documentTemplates };
};
