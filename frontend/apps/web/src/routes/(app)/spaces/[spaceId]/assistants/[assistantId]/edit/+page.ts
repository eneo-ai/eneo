import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";
import { hasPermission } from "$lib/core/hasPermission.js";
import {
  emptySkillBindingCatalogPage,
  loadSkillBindingCatalogPage
} from "$lib/features/skills/skillBindingCatalog";

export const load = async (event) => {
  event.depends("space:skills");
  event.depends("organization:skills");
  const { eneo, currentSpace, user } = await event.parent();
  const canReadSkills = currentSpace.skill_permissions?.includes("read") ?? false;
  const supportsDirectSkills =
    !currentSpace.personal || currentSpace.default_assistant?.id !== event.params.assistantId;
  // Widgets are listed only to the people who manage them; for anyone else
  // the published-as-widget notice cannot be shown.
  const canReadWidgets = user ? hasPermission(user)({ anyOf: ["widgets", "admin"] }) : false;
  const [assistant, mcpServers, promptGuideAvailability, skills, skillConfiguration, widgets] =
    await Promise.all([
      eneo.assistants.get({ id: event.params.assistantId }),
      eneo.assistants.listMCPServers({ id: event.params.assistantId }),
      // Prefetch so the toolbar's Prompt Guide button can render with the
      // correct enabled/disabled state on first paint — same cadence as the
      // History button next to it. Fail-closed: a thrown availability check
      // hides the button rather than risking a misleading enabled state.
      eneo.helpAssistants.runs
        .availability({ kind: "prompt_guide", target_id: event.params.assistantId })
        .catch(() => null),
      canReadSkills && supportsDirectSkills
        ? loadSkillBindingCatalogPage({
            eneo,
            spaceId: currentSpace.id,
            organizationSpace: currentSpace.organization === true
          })
        : Promise.resolve(emptySkillBindingCatalogPage()),
      canReadSkills && supportsDirectSkills
        ? eneo.skills.getAssistantConfiguration({
            spaceId: currentSpace.id,
            assistantId: event.params.assistantId
          })
        : Promise.resolve({ bindings: [], runtime: null }),
      canReadWidgets
        ? eneo.widgets.list({ spaceId: currentSpace.id }).catch(() => [])
        : Promise.resolve([])
    ]);

  // Help assistants are edited in the admin UI, not in a space. If someone
  // lands here via a stale link, send them to the help-assistants admin page.
  if ((assistant as { is_help_assistant?: boolean }).is_help_assistant) {
    redirect(307, resolve("/admin/help-assistants"));
  }

  return {
    assistant,
    mcpServers: mcpServers.items || [],
    promptGuideAvailability,
    skills,
    skillBindings: skillConfiguration.bindings,
    skillRuntime: skillConfiguration.runtime,
    supportsDirectSkills,
    // Visitors get the assistant as configured, tools included.
    servesActiveWidget: widgets.some(
      (widget) => widget.target_id === event.params.assistantId && widget.status === "active"
    )
  };
};
