export const load = async (event) => {
  // Permissions are checked in parent layout (+layout.ts)
  const { eneo } = await event.parent();

  // Load available models (tenant-wide, no space required)
  const models = await eneo.models.list();

  return {
    eneo,
    completionModels: models.completionModels || []
  };
};
