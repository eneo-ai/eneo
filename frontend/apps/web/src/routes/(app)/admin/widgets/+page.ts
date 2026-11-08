import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  const [policy, templates, overview] = await Promise.all([
    eneo.widgets.policy.get(),
    eneo.widgets.templates.list(),
    eneo.widgets.overview()
  ]);
  return { policy, templates, overview };
};
