import { fileHandleId } from "$lib/components/markdown/FileImageContext";

/** Path of a signed file reference URL, mirroring the backend's parser. */
const FILE_DOWNLOAD_PATH = /\/api\/v1\/files\/([0-9a-fA-F-]{36})\/original\/download\/?$/;

/** The id of the file a signed reference URL points at, or null for any other value. */
export function referencedFileId(url: unknown): string | null {
  if (typeof url !== "string") return null;
  const handle = fileHandleId(url);
  if (handle) return handle;
  try {
    return FILE_DOWNLOAD_PATH.exec(new URL(url).pathname)?.[1] ?? null;
  } catch {
    return null;
  }
}
