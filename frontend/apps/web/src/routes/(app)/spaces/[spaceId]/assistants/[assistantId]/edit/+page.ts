export const load = async (event) => {
  const { eneo } = await event.parent();
  const [assistant, mcpServers] = await Promise.all([
    eneo.assistants.get({ id: event.params.assistantId }),
    eneo.assistants.listMCPServers({ id: event.params.assistantId })
  ]);

  return {
    assistant,
    mcpServers: mcpServers.items || []
  };
};
