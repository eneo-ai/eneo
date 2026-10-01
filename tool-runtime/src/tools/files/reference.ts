import { z } from "zod";
import { ToolError } from "../../errors";
import type { DownloadPolicy } from "../tabular/config";
import { downloadFile } from "../tabular/download";
import type { CallContext } from "../types";

// Eneo's signed original-download link: /api/v1/files/{id}/original/download/?token=…
const FILE_PATH = /^\/api\/v1\/files\/([0-9a-f-]{36})\/original\/download\/?$/;

/** A file the model names by its signed Eneo URL and filename, both passed unchanged. */
function referenceTo(extensions: readonly string[]) {
  const list = extensions.map((extension) => `.${extension}`).join(" and ");
  return z
    .object({
      url: z
        .string()
        .min(1)
        .max(8192)
        .describe("The file's signed Eneo URL, exactly as given in the attachment reference."),
      filename: z
        .string()
        .max(200)
        .regex(
          new RegExp(`^[^\\x00-\\x1f/\\\\]+\\.(${extensions.join("|")})$`, "i"),
          `Only ${list} files are supported`,
        )
        .describe(`The file's name, ending in ${list}.`),
    })
    .strict();
}
/** A table source: CSV or XLSX. */
export const fileReference = referenceTo(["csv", "xlsx"]);
/** A Word document used as a template. */
export const documentReference = referenceTo(["docx"]);
export type FileReference = z.infer<typeof fileReference>;

export type ReferenceAccess = {
  /** Optional operator limit (TOOL_RUNTIME_FILE_ORIGINS) on the origin Eneo sends. */
  allowedFileOrigins: string[];
  maxBytes: number;
  timeoutMs: number;
  /** Replaceable in tests; production downloads through the pinned, bounded client. */
  download?: typeof downloadFile;
};

/**
 * Downloads a file through its signed Eneo URL. The URL must point at the origin Eneo sent
 * with this call (never one chosen by the model) and at the original-download path, and the
 * download happens on every call, so Eneo checks access each time.
 */
export async function fetchReference(
  ref: FileReference,
  ctx: CallContext,
  access: ReferenceAccess,
): Promise<{ bytes: Buffer; contentType: string; isXlsx: boolean }> {
  let url: URL;
  try {
    url = new URL(ref.url);
  } catch {
    throw new ToolError("INVALID_URL", "Pass the attachment's signed URL unchanged.");
  }
  const origin = ctx.fileOrigin;
  if (!origin)
    throw new ToolError(
      "FILE_ORIGIN_UNKNOWN",
      "Eneo did not say where its file links point. Set FILE_REFERENCE_BASE_URL (or PUBLIC_ORIGIN) on the Eneo backend.",
    );
  if (access.allowedFileOrigins.length && !access.allowedFileOrigins.includes(origin))
    throw new ToolError(
      "FILE_ORIGIN_NOT_ALLOWED",
      "Eneo's file origin is not in this runtime's TOOL_RUNTIME_FILE_ORIGINS. Align the two settings.",
    );
  if (url.searchParams.get("token") === "REDACTED")
    throw new ToolError(
      "STALE_REFERENCE",
      "This link was copied from conversation history, where its token is removed. Use the url from the file's attachment reference in the current request, exactly as given. Do not ask the user to upload the file again.",
    );
  if (url.origin !== origin || !FILE_PATH.test(url.pathname) || !url.searchParams.get("token"))
    throw new ToolError(
      "INVALID_URL",
      "Only signed Eneo attachment URLs are accepted. Pass the url from the attachment reference unchanged.",
    );
  const policy: DownloadPolicy = {
    max_upload_bytes: access.maxBytes,
    download_timeout_ms: access.timeoutMs,
    allowed_origins: [{ origin, allow_private: true }],
  };
  const file = await (access.download ?? downloadFile)(ref.url, policy);
  return {
    bytes: file.bytes,
    contentType: file.contentType,
    isXlsx: ref.filename.toLowerCase().endsWith(".xlsx"),
  };
}
