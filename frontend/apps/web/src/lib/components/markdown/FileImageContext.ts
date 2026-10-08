import { getContext, setContext } from "svelte";

const key = Symbol("markdown-file-images");

// How Eneo names a file without credentials: eneo-file:<its id without dashes>.
const FILE_HANDLE =
  /^eneo-file:([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})$/;

/** The id of the file a handle names, or null for any other value. */
export function fileHandleId(value: unknown): string | null {
  const handle = typeof value === "string" ? FILE_HANDLE.exec(value) : null;
  return handle ? handle.slice(1).join("-") : null;
}

/**
 * Lets the Markdown below show Eneo files as images: a document names an image
 * by its file handle, and `urlOf` gives a link the reader may load it from, or
 * undefined while there is none. Markdown without this shows the alt text.
 */
export function setFileImageUrls(urlOf: (fileId: string) => string | undefined) {
  setContext(key, urlOf);
}

export function getFileImageUrls(): ((fileId: string) => string | undefined) | undefined {
  return getContext<((fileId: string) => string | undefined) | undefined>(key);
}
