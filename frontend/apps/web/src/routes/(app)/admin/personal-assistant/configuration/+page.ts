/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:governance-policy");
  event.depends("admin:prompt-library");
  const { eneo } = await event.parent();
  const [policy, models, mcpSettings, promptLibrary, modelProviders] = await Promise.all([
    eneo.governancePolicy.get(),
    eneo.models.list(),
    eneo.mcpServers.listSettings(),
    eneo.promptLibrary.list(),
    eneo.modelProviders.list()
  ]);
  return { policy, models, mcpSettings, promptLibrary, modelProviders };
};
