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
const BACKEND_TIMEOUT_MS = 2500;
const FOUND_TTL_MS = 60_000;
const MISSING_TTL_MS = 5_000;
const MAX_CACHED = 1000;

type Cached = {
  /** Infinity while the backend answers, so requests that arrive meanwhile share it. */
  expires: number;
  settings: Promise<WidgetLauncherSettings | null>;
};

// Every page view on every host site asks, so one backend request per
// widget and minute serves them all.
const cache = new Map<string, Cached>();

class BackendTimeout extends Error {}

async function fetchSettings(
  publicId: string,
  fetch: typeof globalThis.fetch
): Promise<WidgetLauncherSettings | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);
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

function cachedSettings(publicId: string, fetch: typeof globalThis.fetch): Cached {
  const hit = cache.get(publicId);
  if (hit && hit.expires > Date.now()) return hit;
  cache.delete(publicId);
  if (cache.size >= MAX_CACHED) cache.delete(cache.keys().next().value!);
  const entry: Cached = { expires: Infinity, settings: fetchSettings(publicId, fetch) };
  cache.set(publicId, entry);
  entry.settings.then(
    (settings) => {
      entry.expires = Date.now() + (settings ? FOUND_TTL_MS : MISSING_TTL_MS);
    },
    () => {
      if (cache.get(publicId) === entry) cache.delete(publicId);
    }
  );
  return entry;
}

/**
 * `GET /widget/settings/wgt_…` — the language, position and colours the
 * loader needs before it shows the launcher. Cached as briefly as the
 * widget's configuration; a paused, draft or unknown widget answers 404 and
 * the loader falls back to its attributes, as it does on a slow backend.
 */
export const GET: RequestHandler = async ({ params, fetch }) => {
  const entry = cachedSettings(params.publicId, fetch);
  let settings: WidgetLauncherSettings | null;
  try {
    settings = await entry.settings;
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
  // A browser keeps it only as long as the server still does, so an edit
  // reaches sites within a minute.
  const left = Math.min(entry.expires - Date.now(), FOUND_TTL_MS);
  return json(settings, {
    headers: {
      ...HEADERS,
      "cache-control": `public, max-age=${Math.max(0, Math.ceil(left / 1000))}`
    }
  });
};
