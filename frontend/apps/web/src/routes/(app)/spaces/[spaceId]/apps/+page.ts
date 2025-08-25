import { error } from '@sveltejs/kit';

export const load = async (event) => {
  const { intric, currentSpace } = await event.parent();

  const isOrgSpace = currentSpace.organization === true

  if (isOrgSpace) {
    throw error(404);
  }

  const allTemplates = await intric.templates.list({ filter: 'apps' });

  return { allTemplates };
};