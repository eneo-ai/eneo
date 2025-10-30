export const load = async (event) => {
  // Permissions are checked in parent layout (+layout.ts)
  const { intric } = await event.parent();

  // Load available models (tenant-wide, no space required)
  const models = await intric.models.list();

  return {
    intric,
    completionModels: models.completionModels || []
  };
};
