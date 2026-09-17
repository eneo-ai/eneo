import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  const template = await eneo.widgets.templates.get({ id: event.params.templateId });
  return { template };
};
