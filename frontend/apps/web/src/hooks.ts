import type { Reroute } from "@sveltejs/kit";
import { deLocalizeUrl } from "$lib/paraglide/runtime";

// Must leave the path's percent-encoding as valid or invalid as it was:
// SvelteKit decodes both the request path and what this returns, while
// malformedPathHandle (hooks.server.ts) checks only the request path. Give a
// new rewrite its own case in hooks.server.path.test.ts.
export const reroute: Reroute = (request) => {
  return deLocalizeUrl(request.url).pathname;
};
