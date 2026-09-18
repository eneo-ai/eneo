import { error } from "@sveltejs/kit";
import { createWidgetClient, EneoError } from "@eneo/eneo-js";
import { frameAncestorsFor } from "$lib/core/csp";
import { getBackendUrl } from "$lib/core/environment.server";
import { PREVIEW_QUERY } from "$lib/features/widget/preview";
import type { PageServerLoad } from "./$types";

/** Only a syntactically valid origin may become the postMessage peer. */
function parseHostOrigin(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.origin === raw ? url.origin : null;
  } catch {
    return null;
  }
}

function parseScheme(raw: string | null): "light" | "dark" | "auto" | null {
  return raw === "light" || raw === "dark" || raw === "auto" ? raw : null;
}

export const load: PageServerLoad = async ({ params, url, fetch, locals, setHeaders }) => {
  const baseUrl = getBackendUrl() ?? "";
  const client = createWidgetClient({ baseUrl, publicId: params.publicId, fetch });
  const standalone = url.searchParams.get("mode") === "full";
  // The admin page's live preview: the token is in the fragment, so the
  // configuration is fetched in the browser and only Eneo itself may frame it.
  const preview = url.searchParams.get(PREVIEW_QUERY) === "1";

  let config = null;
  if (!preview) {
    try {
      config = await client.config();
    } catch (e) {
      if (e instanceof EneoError && e.status === 404) {
        error(404);
      }
      throw e;
    }
  }

  // The browser enforces where this page may render. The stand-alone page has
  // no reason to be framed at all.
  locals.frameAncestors =
    standalone || !config ? "'self'" : frameAncestorsFor(config.frame_ancestors);

  const hostScheme = parseScheme(url.searchParams.get("scheme"));
  const pinned = config?.theme.color_scheme;
  locals.embedScheme =
    pinned === "light" || pinned === "dark"
      ? pinned
      : hostScheme === "light" || hostScheme === "dark"
        ? hostScheme
        : "system";

  setHeaders({
    "cache-control": "no-store",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "x-content-type-options": "nosniff"
  });

  return {
    config,
    publicId: params.publicId,
    baseUrl,
    hostOrigin: standalone ? null : parseHostOrigin(url.searchParams.get("origin")),
    preview,
    hostScheme,
    standalone
  };
};
