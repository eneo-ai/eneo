/** Path of a signed file reference URL, mirroring the backend's parser. */
const FILE_DOWNLOAD_PATH = /\/api\/v1\/files\/([0-9a-fA-F-]{36})\/original\/download\/?$/;

/** The id of the file a signed reference URL points at, or null for any other value. */
export function referencedFileId(url: unknown): string | null {
  if (typeof url !== "string") return null;
  const handle =
    /^eneo-file:([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})$/.exec(url);
  if (handle) return handle.slice(1).join("-");
  try {
    return FILE_DOWNLOAD_PATH.exec(new URL(url).pathname)?.[1] ?? null;
  } catch {
    return null;
  }
}
