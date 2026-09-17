import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  const [policy, templates] = await Promise.all([
    eneo.widgets.policy.get(),
    eneo.widgets.templates.list()
  ]);
  return { policy, templates };
};
