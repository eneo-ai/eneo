export const load = async (event) => {
  const { intric } = await event.parent();
  const [assistant, mcpServers] = await Promise.all([
    intric.assistants.get({ id: event.params.assistantId }),
    intric.assistants.listMCPServers({ id: event.params.assistantId })
  ]);

  return {
    assistant,
    mcpServers: mcpServers.items || []
  };
};
