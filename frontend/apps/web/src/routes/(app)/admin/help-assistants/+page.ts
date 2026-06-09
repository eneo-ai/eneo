/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:help-assistants:load");

  // `roles` = the help assistants currently installed for this tenant (the
  // table rows). `templates` = the shipped blueprints not yet installed (the
  // "Add help assistant" picker). A kind moves from `templates` to `roles`
  // when installed, and back when uninstalled. Each kind owns its own UI hook
  // elsewhere (e.g. the Prompt Guide button on assistant settings pages); this
  // page only installs / configures / removes them.
  const [roles, templates] = await Promise.all([
    intric.helpAssistants.admin.listRoles(),
    intric.helpAssistants.admin.listTemplates()
  ]);

  return { roles, templates };
};
