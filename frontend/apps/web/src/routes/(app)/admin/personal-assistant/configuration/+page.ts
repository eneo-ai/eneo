/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:personal-assistant-policy");
  const { intric } = await event.parent();
  const [policy, models, mcpSettings, promptLibrary, modelProviders] = await Promise.all([
    intric.personalAssistantPolicy.get(),
    intric.models.list(),
    intric.mcpServers.listSettings(),
    intric.promptLibrary.list(),
    intric.modelProviders.list()
  ]);
  return { policy, models, mcpSettings, promptLibrary, modelProviders };
};
