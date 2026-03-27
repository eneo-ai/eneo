import { error } from '@sveltejs/kit';

export const load = async (event) => {
  // Permissions are checked in parent layout (+layout.ts)
  const { eneo } = await event.parent();

  // Fetch the template data
  const templates = await eneo.templates.admin.listApps();
  const template = templates.items?.find((t: any) => t.id === event.params.id);

  if (!template) {
    throw error(404, 'Template not found');
  }

  // Load available models (tenant-wide, no space required)
  const models = await eneo.models.list();

  return {
    eneo,
    template,
    completionModels: models.completionModels || []
  };
};
