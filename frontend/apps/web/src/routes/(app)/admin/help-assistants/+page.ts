/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:help-assistants:load");

  // v1 has a single helper kind (prompt_guide); the archivable list is scoped
  // to it. The role table itself iterates over `roles`, so future kinds surface
  // there without code changes (step 031 / PRD §9). Assignment history is no
  // longer shown here — those actions are audit-logged and surface under
  // Granskningsloggar (/admin/audit-logs) like every other admin action.
  const [roles, archivable] = await Promise.all([
    intric.helpAssistants.admin.listRoles(),
    intric.helpAssistants.admin.listArchivable({ kind: "prompt_guide" })
  ]);

  return { roles, archivable };
};
