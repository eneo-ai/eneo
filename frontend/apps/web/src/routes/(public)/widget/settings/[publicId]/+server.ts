import { createWidgetClient, EneoError } from "@eneo/eneo-js";
import { json } from "@sveltejs/kit";
import { getBackendUrl } from "$lib/core/environment.server";
import { launcherSettings } from "$lib/features/widget/launcherSettings";
import type { RequestHandler } from "./$types";

// Read by the loader on any host page, so CORS is open; nothing here is
// more than the widget's public configuration already shows.
const HEADERS = {
  "access-control-allow-origin": "*",
  "cross-origin-resource-policy": "cross-origin",
  "x-content-type-options": "nosniff"
};

/**
 * `GET /widget/settings/wgt_…` — the language, position and colours the
 * loader needs before it shows the launcher. Cached as briefly as the
 * widget's configuration; a paused, draft or unknown widget answers 404 and
 * the loader falls back to its attributes.
 */
export const GET: RequestHandler = async ({ params, fetch }) => {
  const client = createWidgetClient({
    baseUrl: getBackendUrl() ?? "",
    publicId: params.publicId,
    fetch
  });
  try {
    const config = await client.config();
    return json(launcherSettings(config), {
      headers: { ...HEADERS, "cache-control": "public, max-age=60" }
    });
  } catch (error) {
    if (error instanceof EneoError && error.status === 404) {
      return new Response(null, {
        status: 404,
        headers: { ...HEADERS, "cache-control": "no-store" }
      });
    }
    throw error;
  }
};
