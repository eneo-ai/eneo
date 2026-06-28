import { error } from "@sveltejs/kit";

export const load = async (event) => {
  // Explicitly depend on settings changes for template visibility
  event.depends("app:settings");
  const { eneo, currentSpace } = await event.parent();
  const allTemplates = await eneo.templates.list({ filter: "apps" });

  const isOrgSpace = currentSpace.organization === true;

  if (isOrgSpace) {
    throw error(404);
  }

  return { allTemplates };
};
