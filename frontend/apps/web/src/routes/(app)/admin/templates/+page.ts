/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  event.depends("admin:templates:load");

  let assistantTemplates: any = { items: [] };
  let appTemplates: any = { items: [] };
  let deletedAssistantTemplates: any = { items: [] };
  let deletedAppTemplates: any = { items: [] };

  try {
    assistantTemplates = await eneo.templates.admin.listAssistants();
  } catch (error) {
    console.error('Failed to fetch assistant templates:', error);
  }

  try {
    appTemplates = await eneo.templates.admin.listApps();
  } catch (error) {
    console.error('Failed to fetch app templates:', error);
  }

  try {
    deletedAssistantTemplates = await eneo.templates.admin.listDeletedAssistants();
  } catch (error) {
    console.error('Failed to fetch deleted assistant templates:', error);
  }

  try {
    deletedAppTemplates = await eneo.templates.admin.listDeletedApps();
  } catch (error) {
    console.error('Failed to fetch deleted app templates:', error);
  }

  return {
    assistantTemplates: assistantTemplates?.items ?? [],
    appTemplates: appTemplates?.items ?? [],
    deletedTemplates: [
      ...(deletedAssistantTemplates?.items ?? []),
      ...(deletedAppTemplates?.items ?? [])
    ]
  };
};
