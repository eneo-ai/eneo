import { getWidgetLoaderBundle } from "$lib/server/widget-loader";
import type { PageServerLoad } from "./$types";

/** Only what the snippet needs; the loader source itself stays on the server. */
export const load: PageServerLoad = async () => {
  const bundle = await getWidgetLoaderBundle();
  return {
    release: bundle
      ? { version: bundle.version, channel: bundle.channel, integrity: bundle.integrity }
      : null
  };
};
