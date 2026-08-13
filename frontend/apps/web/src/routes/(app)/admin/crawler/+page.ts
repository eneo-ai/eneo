import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  event.depends("admin:crawler:diagnostics");

  return {
    diagnostics: await eneo.crawler.diagnostics()
  };
};
