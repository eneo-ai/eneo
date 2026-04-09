/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:templates:load");

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let assistantTemplates: any = { items: [] };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let appTemplates: any = { items: [] };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let deletedAssistantTemplates: any = { items: [] };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let deletedAppTemplates: any = { items: [] };

  try {
    assistantTemplates = await intric.templates.admin.listAssistants();
  } catch (error) {
    console.error("Failed to fetch assistant templates:", error);
  }

  try {
    appTemplates = await intric.templates.admin.listApps();
  } catch (error) {
    console.error("Failed to fetch app templates:", error);
  }

  try {
    deletedAssistantTemplates = await intric.templates.admin.listDeletedAssistants();
  } catch (error) {
    console.error("Failed to fetch deleted assistant templates:", error);
  }

  try {
    deletedAppTemplates = await intric.templates.admin.listDeletedApps();
  } catch (error) {
    console.error("Failed to fetch deleted app templates:", error);
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
