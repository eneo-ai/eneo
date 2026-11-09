import type { ParamMatcher } from "@sveltejs/kit";

/**
 * A widget's public id as the backend issues it (`PUBLIC_ID_RE`). SvelteKit
 * decodes route parameters before `load` runs, so without this matcher an
 * address like `/embed/wgt_x%2F..%2F..%2Ffoo` reaches the proxy as a value
 * with path segments in it; the route does not exist for anything else.
 */
export const match: ParamMatcher = (param) => /^wgt_[0-9A-Za-z]{22}$/.test(param);
