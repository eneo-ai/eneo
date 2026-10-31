import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { proxiedDownloadPath } from "@/features/files/signed-file-url";

export async function signedInfoBlobOriginalUrl(
  api: EneoClient,
  blobId: string,
  signal: AbortSignal
): Promise<string> {
  const signed = await unwrap(
    api.POST("/api/v1/info-blobs/{id}/original/signed-url/", {
      params: { path: { id: blobId } },
      body: { expires_in: 3600, content_disposition: "attachment" },
      signal
    })
  );
  return proxiedDownloadPath(signed.url, blobId, "info-blob-original");
}
