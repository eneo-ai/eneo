import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  const policy = await eneo.widgets.policy.get();
  return { policy };
};
