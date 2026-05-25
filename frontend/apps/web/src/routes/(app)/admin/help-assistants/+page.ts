/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:help-assistants:load");

  const [roles, history] = await Promise.all([
    intric.helpAssistants.admin.listRoles(),
    intric.helpAssistants.admin.listHistory({ kind: "prompt_guide" })
  ]);

  return { roles, history };
};
