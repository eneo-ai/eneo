import { createWidgetClient, EneoError } from "@eneo/eneo-js";
import { json } from "@sveltejs/kit";
import { getBackendUrl } from "$lib/core/environment.server";
import {
  launcherSettings,
  type WidgetLauncherSettings
} from "$lib/features/widget/launcherSettings";
import type { RequestHandler } from "./$types";

// Read by the loader on any host page, so CORS is open; nothing here is
// more than the widget's public configuration already shows.
const HEADERS = {
  "access-control-allow-origin": "*",
  "cross-origin-resource-policy": "cross-origin",
  "x-content-type-options": "nosniff"
};

// The loader stops waiting after three seconds; answer before it does.
const RESPONSE_DEADLINE_MS = 2500;

class BackendTimeout extends Error {}

async function fetchSettings(
  publicId: string,
  fetch: typeof globalThis.fetch
): Promise<WidgetLauncherSettings | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), RESPONSE_DEADLINE_MS);
  const client = createWidgetClient({
    baseUrl: getBackendUrl() ?? "",
    publicId,
    fetch: (input, init) => fetch(input, { ...init, signal: controller.signal })
  });
  try {
    return launcherSettings(await client.config());
  } catch (error) {
    if (controller.signal.aborted) throw new BackendTimeout();
    if (error instanceof EneoError && error.status === 404) return null;
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * `GET /widget/settings/wgt_…` — the language, position and colours the
 * loader needs before it shows the launcher. Every new page view checks the
 * current state, so a pause or unpublish hides the launcher immediately.
 * A slow or failed request still falls back to the element's attributes.
 */
export const GET: RequestHandler = async ({ params, fetch }) => {
  let settings: WidgetLauncherSettings | null;
  try {
    settings = await fetchSettings(params.publicId, fetch);
  } catch (error) {
    if (!(error instanceof BackendTimeout)) throw error;
    return new Response(null, {
      status: 503,
      headers: { ...HEADERS, "cache-control": "no-store", "retry-after": "5" }
    });
  }
  if (!settings) {
    return new Response(null, {
      status: 404,
      headers: { ...HEADERS, "cache-control": "no-store" }
    });
  }
  return json(settings, {
    headers: { ...HEADERS, "cache-control": "no-store" }
  });
};
