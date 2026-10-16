// How Eneo names a file without credentials: eneo-file:<its id without dashes>.
const FILE_HANDLE =
  /^eneo-file:([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})$/i;

/** Path of a signed file reference URL, mirroring the backend's parser. */
const FILE_DOWNLOAD_PATH = /\/api\/v1\/files\/([0-9a-fA-F-]{36})\/original\/download\/?$/;

/** The id a file handle (`eneo-file:<hex>`) names, or null for any other value. */
export function fileHandleId(value: unknown): string | null {
  const handle = typeof value === "string" ? FILE_HANDLE.exec(value) : null;
  return handle ? handle.slice(1).join("-").toLowerCase() : null;
}

/** The id of the file a handle or signed reference URL points at, or null for any other value. */
export function referencedFileId(url: unknown): string | null {
  if (typeof url !== "string") return null;
  const handle = fileHandleId(url);
  if (handle) return handle;
  try {
    return FILE_DOWNLOAD_PATH.exec(new URL(url).pathname)?.[1]?.toLowerCase() ?? null;
  } catch {
    return null;
  }
}
