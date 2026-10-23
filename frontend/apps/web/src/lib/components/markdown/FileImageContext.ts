// How Eneo names a file without credentials: eneo-file:<its id without dashes>.
const FILE_HANDLE =
  /^eneo-file:([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})$/;

/** The id of the file a handle names, or null for any other value. */
export function fileHandleId(value: unknown): string | null {
  const handle = typeof value === "string" ? FILE_HANDLE.exec(value) : null;
  return handle ? handle.slice(1).join("-") : null;
}
