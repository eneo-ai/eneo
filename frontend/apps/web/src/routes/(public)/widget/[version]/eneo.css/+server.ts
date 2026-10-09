import { error } from "@sveltejs/kit";
import { getWidgetLoaderBundle, resolveLoaderVariant } from "$lib/server/widget-loader";
import type { RequestHandler } from "./$types";

const CHANNEL_CACHE = "public, max-age=3600";
const PINNED_CACHE = "public, max-age=31536000, immutable";

/** External shadow-root styles for hosts whose CSP disallows inline CSS. */
export const GET: RequestHandler = async ({ params, request, setHeaders }) => {
  const current = await getWidgetLoaderBundle();
  if (!current) {
    return new Response(null, { status: 503, headers: { "retry-after": "60" } });
  }
  const bundle = await getWidgetLoaderBundle(params.version);
  if (!bundle?.cssSource || !bundle.cssIntegrity) error(404);
  const variant = resolveLoaderVariant(bundle, params.version);
  if (!variant) error(404);

  const etag = `"${bundle.cssIntegrity}"`;
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
  return new Response(bundle.cssSource, {
    headers: { "content-type": "text/css; charset=utf-8" }
  });
};
