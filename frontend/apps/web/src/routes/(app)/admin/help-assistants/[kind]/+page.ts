/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:help-assistant:settings");

  const kind = event.params.kind;

  // Resolve the installed helper for this kind, then load its assistant +
  // the org-space (for the completion-model list and retention inheritance).
  // Help assistants live in the org-space; an admin can read it.
  const role = await intric.helpAssistants.admin.getRole({ kind: kind as "prompt_guide" });
  if (!role) {
    throw error(404);
  }

  const [assistant, orgSpace] = await Promise.all([
    intric.assistants.get({ id: role.assistant_id }),
    intric.spaces.getOrganizationSpace()
  ]);

  // The Prompt Guide button is hooked into *other* helpers' settings (so an
  // admin can use it to draft their instructions), never the Prompt Guide's
  // own page. Prefetch availability only when this is not the Prompt Guide.
  const promptGuideAvailability =
    kind === "prompt_guide"
      ? null
      : await intric.helpAssistants.runs
          .availability({ kind: "prompt_guide", target_id: assistant.id })
          .catch(() => null);

  return { kind, role, assistant, orgSpace, promptGuideAvailability };
};
