import { error } from "@sveltejs/kit";
import { getWidgetLoaderBundle, resolveLoaderVariant } from "$lib/server/widget-loader";
import type { RequestHandler } from "./$types";

const CHANNEL_CACHE = "public, max-age=3600";
const PINNED_CACHE = "public, max-age=31536000, immutable";

/**
 * `GET /widget/v1/eneo.js` — the script host sites include. The floating
 * channel follows releases; the pinned `/widget/1.2.3/eneo.js` never changes
 * and carries the SRI hash printed by the admin snippet. CORS is open on
 * purpose: `integrity` only works on scripts fetched with `crossorigin`.
 */
export const GET: RequestHandler = async ({ params, request, setHeaders }) => {
  const bundle = await getWidgetLoaderBundle();
  if (!bundle) {
    // The package has not been built; see packages/widget-loader/README.md.
    return new Response(null, { status: 503, headers: { "retry-after": "60" } });
  }
  const variant = resolveLoaderVariant(bundle, params.version);
  if (!variant) {
    error(404);
  }

  const etag = `"${bundle.integrity}"`;
  setHeaders({
    "cache-control": variant === "pinned" ? PINNED_CACHE : CHANNEL_CACHE,
    "access-control-allow-origin": "*",
    "cross-origin-resource-policy": "cross-origin",
    "x-content-type-options": "nosniff",
    "x-eneo-widget-version": bundle.version,
    etag
  });
  if (request.headers.get("if-none-match") === etag) {
    return new Response(null, { status: 304 });
  }
  return new Response(bundle.source, {
    headers: { "content-type": "text/javascript; charset=utf-8" }
  });
};
