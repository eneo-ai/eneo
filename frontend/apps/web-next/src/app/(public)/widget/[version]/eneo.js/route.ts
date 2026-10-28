import { loaderAssetResponse } from "@/lib/server/widget-loader";

export const dynamic = "force-dynamic";

/** The loader script host sites include; see lib/server/widget-loader.ts. */
export async function GET(request: Request, { params }: RouteContext<"/widget/[version]/eneo.js">) {
  const { version } = await params;
  return loaderAssetResponse(request, version, "js");
}
