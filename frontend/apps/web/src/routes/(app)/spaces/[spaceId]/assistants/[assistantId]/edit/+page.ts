export const load = async (event) => {
  const { intric } = await event.parent();
  const [assistant, mcpServers, promptGuideAvailability] = await Promise.all([
    intric.assistants.get({ id: event.params.assistantId }),
    intric.assistants.listMCPServers({ id: event.params.assistantId }),
    // Prefetch so the toolbar's Prompt Guide button can render with the
    // correct enabled/disabled state on first paint — same cadence as the
    // History button next to it. Fail-closed: a thrown availability check
    // hides the button rather than risking a misleading enabled state.
    intric.helpAssistants.runs
      .availability({ kind: "prompt_guide", target_id: event.params.assistantId })
      .catch(() => null)
  ]);

  return {
    assistant,
    mcpServers: mcpServers.items || [],
    promptGuideAvailability
  };
};
