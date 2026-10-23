import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";

/**
 * Issue a short-lived file URL and consume it through the same-origin proxy.
 * The backend's absolute URL can name a Docker-only host; only its expected
 * download path and signed query belong in the browser.
 */
export async function signedFileUrl(
  api: EneoClient,
  fileId: string,
  disposition: "inline" | "attachment"
): Promise<string> {
  const signed = await unwrap(
    api.POST("/api/v1/files/{id}/signed-url/", {
      params: { path: { id: fileId } },
      body: { expires_in: 3600, content_disposition: disposition }
    })
  );
  const parsed = new URL(signed.url);
  if (
    parsed.pathname !== `/api/v1/files/${encodeURIComponent(fileId)}/download/` ||
    !parsed.searchParams.get("token")
  ) {
    throw new Error("Unexpected signed file URL");
  }
  return `/api/eneo${parsed.pathname}${parsed.search}`;
}
