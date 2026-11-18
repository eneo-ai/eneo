import { PREVIEW_QUERY } from "./preview";

/** What the backend accepts for the footer link: an absolute http(s) URL. */
export function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return (url.protocol === "http:" || url.protocol === "https:") && url.hostname.length > 0;
  } catch {
    return false;
  }
}

/** The host name of a link, shown when a footer link has no label of its own. */
export function linkHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** Preserve the loader's public query parameters while typing preview reload dependencies. */
export function embedSearch(search: Record<string, unknown>) {
  const text = (key: string) => (typeof search[key] === "string" ? search[key] : undefined);
  return {
    preview: text(PREVIEW_QUERY),
    origin: text("origin"),
    scheme: text("scheme"),
    mode: text("mode")
  };
}

/** Only an exact origin may become the postMessage peer. */
export function parseHostOrigin(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.origin === raw ? url.origin : null;
  } catch {
    return null;
  }
}

export function parseScheme(raw: string | null): "light" | "dark" | "auto" | null {
  return raw === "light" || raw === "dark" || raw === "auto" ? raw : null;
}
