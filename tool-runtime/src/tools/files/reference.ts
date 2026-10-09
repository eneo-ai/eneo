import { createHash } from "node:crypto";
import { fileCache } from "./cache";
import { checkCancellation } from "../../work";
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
export const fileReference = referenceTo(["csv", "tsv", "xlsx"]);
/** Raster images embedded in documents; bytes are validated in the sandbox. */
export const imageReference = referenceTo(["png", "jpg", "jpeg"]);
/** A Word document used as a template. */
export const documentReference = referenceTo(["docx"]);
/** A template whose {{placeholders}} are filled: Word, plain text or Markdown. */
export const templateReference = referenceTo(["docx", "txt", "md"]);
/** A document created earlier that a new one replaces. */
export const earlierDocumentReference = referenceTo(["md", "docx", "pdf"]);
/** A Markdown document created earlier, whose text is changed in place. */
export const earlierMarkdownReference = referenceTo(["md"]);
/** A workbook created earlier that a new one replaces. */
export const earlierWorkbookReference = referenceTo(["xlsx"]);
export type FileReference = z.infer<typeof fileReference>;

/**
 * The handle of the file a signed Eneo URL points at (eneo-file:<id>), or undefined for any
 * other URL. It names the file without credentials: what a Markdown document keeps of an image.
 */
export function fileHandle(ref: FileReference): string | undefined {
  try {
    const id = FILE_PATH.exec(new URL(ref.url).pathname)?.[1];
    return id && `eneo-file:${id.replaceAll("-", "").toLowerCase()}`;
  } catch {
    return undefined;
  }
}

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
  checkCancellation();
  const cache = ctx.tenantId && ctx.userId ? fileCache() : undefined;
  const identity = createHash("sha256")
    .update([ctx.tenantId, ctx.userId, origin, url.pathname.replace(/\/$/, "")].join("\n"))
    .digest("hex");
  const file = cache
    ? await cache.fetch(identity, (options) =>
        (access.download ?? downloadFile)(ref.url, policy, options),
      )
    : await (access.download ?? downloadFile)(ref.url, policy);
  checkCancellation();
  if (file.bytes.length > access.maxBytes)
    throw new ToolError("FILE_TOO_LARGE", "File exceeds this tool's upload size limit.");
  return {
    bytes: file.bytes,
    contentType: file.contentType,
    isXlsx: ref.filename.toLowerCase().endsWith(".xlsx"),
  };
}
