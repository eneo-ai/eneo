import { API_BASE } from "@/lib/api/base";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";

/**
 * A short-lived URL for a file's exact original bytes (a document is
 * previewed and downloaded as it was made, never as its extracted text),
 * consumed through the same-origin proxy like `signedFileUrl`.
 */
export async function signedOriginalUrl(api: EneoClient, fileId: string): Promise<string> {
  const signed = await unwrap(
    api.POST("/api/v1/files/{id}/original/signed-url/", {
      params: { path: { id: fileId } },
      body: { expires_in: 3600, content_disposition: "attachment" }
    })
  );
  const parsed = new URL(signed.url);
  if (
    parsed.pathname !== `/api/v1/files/${encodeURIComponent(fileId)}/original/download/` ||
    !parsed.searchParams.get("token")
  ) {
    throw new Error("Unexpected signed file URL");
  }
  return `${API_BASE}${parsed.pathname}${parsed.search}`;
}
