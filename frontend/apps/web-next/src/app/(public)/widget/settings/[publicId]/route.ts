import { launcherSettings } from "@/features/widget/launcher-settings";
import { BackendTimeout, fetchPublicConfig } from "@/features/widget/server/public-config";
import { env } from "@/lib/env";

export const dynamic = "force-dynamic";

// Read by the loader on any host page, so CORS is open; nothing here is
// more than the widget's public configuration already shows.
const HEADERS = {
  "access-control-allow-origin": "*",
  "cross-origin-resource-policy": "cross-origin",
  "x-content-type-options": "nosniff",
  "cache-control": "no-store"
};

/**
 * `GET /widget/settings/wgt_…` — the language, position and colours the
 * loader needs before it shows the launcher. Every new page view checks the
 * current state, so a pause or unpublish hides the launcher immediately.
 * A slow or failed request still falls back to the element's attributes.
 */
export async function GET(
  _request: Request,
  { params }: RouteContext<"/widget/settings/[publicId]">
) {
  const { publicId } = await params;
  let config;
  try {
    config = await fetchPublicConfig(publicId);
  } catch (error) {
    if (!(error instanceof BackendTimeout)) throw error;
    return new Response(null, { status: 503, headers: { ...HEADERS, "retry-after": "5" } });
  }
  if (!config) return new Response(null, { status: 404, headers: HEADERS });
  return Response.json(launcherSettings(config, env.APP_ORIGIN), { headers: HEADERS });
}
