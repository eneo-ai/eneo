import { API_BASE } from "@/lib/api/base";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";

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
  return proxiedDownloadPath(signed.url, fileId);
}

const SIGNED_PATHS = {
  download: (fileId: string) => `/api/v1/files/${encodeURIComponent(fileId)}/download/`,
  original: (fileId: string) => `/api/v1/files/${encodeURIComponent(fileId)}/original/download/`
};

/**
 * The same-origin proxy path for a signed URL the backend minted for
 * `fileId`: its download path (`kind` "download") or its original-bytes path
 * ("original"). Anything but that path with a token is refused; the signing
 * host never reaches the browser.
 */
export function proxiedDownloadPath(
  signedUrl: string,
  fileId: string,
  kind: keyof typeof SIGNED_PATHS = "download"
): string {
  const parsed = new URL(signedUrl);
  if (parsed.pathname !== SIGNED_PATHS[kind](fileId) || !parsed.searchParams.get("token")) {
    throw new Error("Unexpected signed file URL");
  }
  return `${API_BASE}${parsed.pathname}${parsed.search}`;
}

/**
 * Hands the file at `href` to the browser to save under `name`, through an
 * anchor in the document (a click on a detached anchor is ignored by some
 * browsers), not a window: no popup blocker stands in the way after an await.
 */
export function saveUrl(href: string, name: string) {
  const anchor = Object.assign(document.createElement("a"), {
    href,
    download: name,
    rel: "noreferrer"
  });
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

/** Hands a file made in this page to the browser to save under `name`. */
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  saveUrl(url, name);
  // The browser reads the blob after the click returns.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * A download that failed: the backend's reason and trace id, or, when the
 * signed URL was refused or the network failed, that the file did not load.
 */
export function toastDownloadError(error: unknown, t: (key: string) => string) {
  if (error instanceof EneoApiError) toastApiError(error, t);
  else toast.error(t("attachment_error_loading_content"));
}
