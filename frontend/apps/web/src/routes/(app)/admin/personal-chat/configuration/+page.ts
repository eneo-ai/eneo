/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:personal-chat-policy");
  const { intric } = await event.parent();
  const [policy, models, mcpSettings, promptLibrary] = await Promise.all([
    intric.personalChatPolicy.get(),
    intric.models.list(),
    intric.mcpServers.listSettings(),
    intric.promptLibrary.list()
  ]);
  return { policy, models, mcpSettings, promptLibrary };
};
