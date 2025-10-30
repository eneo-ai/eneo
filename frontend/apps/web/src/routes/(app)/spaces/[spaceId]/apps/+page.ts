export const load = async (event) => {
  // Explicitly depend on settings changes for template visibility
  event.depends('app:settings');

  const { intric } = await event.parent();
  const allTemplates = await intric.templates.list({ filter: "apps" });

  return {
    allTemplates
  };
};
