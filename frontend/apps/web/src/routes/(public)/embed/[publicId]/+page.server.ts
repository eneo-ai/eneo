import { error } from "@sveltejs/kit";
import { createWidgetClient, EneoError } from "@eneo/eneo-js";
import { frameAncestorsFor } from "$lib/core/csp";
import { getBackendUrl } from "$lib/core/environment.server";
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

  let config;
  try {
    config = await client.config();
  } catch (e) {
    if (e instanceof EneoError && e.status === 404) {
      error(404);
    }
    throw e;
  }

  const standalone = url.searchParams.get("mode") === "full";
  // The browser enforces where this page may render. The stand-alone page has
  // no reason to be framed at all.
  locals.frameAncestors = standalone ? "'self'" : frameAncestorsFor(config.frame_ancestors);

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
    hostScheme: parseScheme(url.searchParams.get("scheme")),
    standalone
  };
};
