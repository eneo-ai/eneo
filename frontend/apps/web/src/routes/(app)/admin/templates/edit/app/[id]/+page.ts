import { error } from '@sveltejs/kit';

export const load = async (event) => {
  // Permissions are checked in parent layout (+layout.ts)
  const { intric } = await event.parent();

  // Fetch the template data
  const templates = await intric.templates.admin.listApps();
  const template = templates.items?.find((t: any) => t.id === event.params.id);

  if (!template) {
    throw error(404, 'Template not found');
  }

  // Load available models (tenant-wide, no space required)
  const models = await intric.models.list();

  return {
    intric,
    template,
    completionModels: models.completionModels || []
  };
};
