import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";

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

  // Help assistants are edited in the admin UI, not in a space. If someone
  // lands here via a stale link, send them to the help-assistants admin page.
  if ((assistant as { is_help_assistant?: boolean }).is_help_assistant) {
    redirect(307, resolve("/admin/help-assistants"));
  }

  return {
    assistant,
    mcpServers: mcpServers.items || [],
    promptGuideAvailability
  };
};
