import { error } from '@sveltejs/kit';

export const load = async (event) => {
  // Explicitly depend on settings changes for template visibility
  event.depends('app:settings');

  const allTemplates = await intric.templates.list({ filter: "assistants" });
  const { intric, currentSpace } = await event.parent();

  const isOrgSpace = currentSpace.organization === true

  if (isOrgSpace) {
    throw error(404);
  }

  const allTemplates = await intric.templates.list({ filter: 'assistants' });

  return { allTemplates };
};