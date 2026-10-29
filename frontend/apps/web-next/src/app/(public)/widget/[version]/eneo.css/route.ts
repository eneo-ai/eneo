import { loaderAssetResponse } from "@/lib/server/widget-loader";

export const dynamic = "force-dynamic";

/** External shadow-root styles for hosts whose CSP disallows inline CSS. */
export async function GET(
  request: Request,
  { params }: RouteContext<"/widget/[version]/eneo.css">
) {
  const { version } = await params;
  return loaderAssetResponse(request, version, "css");
}
