/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:governance-policy");
  event.depends("admin:prompt-library");
  const { intric } = await event.parent();
  const [policy, models, mcpSettings, promptLibrary, modelProviders] = await Promise.all([
    intric.governancePolicy.get(),
    intric.models.list(),
    intric.mcpServers.listSettings(),
    intric.promptLibrary.list(),
    intric.modelProviders.list()
  ]);
  return { policy, models, mcpSettings, promptLibrary, modelProviders };
};
