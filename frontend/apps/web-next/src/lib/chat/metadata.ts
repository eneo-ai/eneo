/** Reading loosely typed chat metadata (provider metadata, MCP `meta`, source URLs). */

import { sanitizeWebHref } from "@/lib/safe-url";

/** A non-blank string, or null for anything else. */
export function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/** The host of an http(s) URL without `www.` ("riksdagen.se"), or null. */
export function hostOf(url: string | null | undefined): string | null {
  const href = sanitizeWebHref(url);
  return href ? new URL(href).hostname.replace(/^www\./, "") || null : null;
}
