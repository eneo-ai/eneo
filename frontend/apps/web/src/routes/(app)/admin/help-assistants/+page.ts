/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:help-assistants:load");

  // v1 has a single helper kind (prompt_guide); history and the archivable
  // list are scoped to it. The role table itself iterates over `roles`, so
  // future kinds surface there without code changes (step 031 / PRD §9).
  const [roles, history, archivable] = await Promise.all([
    intric.helpAssistants.admin.listRoles(),
    intric.helpAssistants.admin.listHistory({ kind: "prompt_guide" }),
    intric.helpAssistants.admin.listArchivable({ kind: "prompt_guide" })
  ]);

  return { roles, history, archivable };
};
