import { createWidgetClient, EneoError } from "@eneo/eneo-js";
import { redirect } from "@sveltejs/kit";
import { frameAncestorsFor, originSource } from "$lib/core/csp";
import { getBackendUrl } from "$lib/core/environment.server";
import { embedLanguageRedirect } from "$lib/features/widget/embedLanguage";
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
  // A paused, archived or unknown widget. The page still renders, as a
  // notice, because the loader on the host site cannot tell a refused frame
  // from a slow one and would otherwise open a blank panel.
  let unavailable = false;
  if (!preview) {
    try {
      config = await client.config();
    } catch (e) {
      if (e instanceof EneoError && e.status === 404) {
        unavailable = true;
      } else {
        throw e;
      }
    }
  }

  // The browser enforces where this page may render. The stand-alone page has
  // no reason to be framed at all; the notice carries nothing worth protecting
  // and the allowed origins are unknown for it, so any site may frame it.
  locals.frameAncestors = unavailable
    ? "*"
    : standalone || !config
      ? "'self'"
      : frameAncestorsFor(config.frame_ancestors);

  // A fixed language wins over the one the loader or a copied link asked
  // for. The frame policy above is already set for the redirect response.
  const localized = config ? embedLanguageRedirect(url, config.language) : null;
  if (localized) redirect(307, localized);

  // The page fetches its API and the organisation's logo from other origins
  // at most; answer Markdown must not be able to reach anything else. The
  // preview has no configuration yet, so it accepts any https image.
  const backendOrigin = originSource(baseUrl);
  const logoOrigin = originSource(config?.theme.logo_url);
  locals.embedSources = {
    img: preview ? ["https:"] : logoOrigin ? [logoOrigin] : [],
    connect: backendOrigin ? [backendOrigin] : []
  };

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
    unavailable,
    publicId: params.publicId,
    baseUrl,
    hostOrigin: standalone ? null : parseHostOrigin(url.searchParams.get("origin")),
    preview,
    hostScheme,
    standalone
  };
};
