/**
 * The admin page frames the embed page of a draft widget with a preview
 * token. The token travels in the URL fragment so it never reaches a server
 * log, and the page loads its configuration client-side with it.
 */

export const PREVIEW_QUERY = "preview";
const FRAGMENT_KEY = "preview";

export function readPreviewToken(hash: string): string | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const token = params.get(FRAGMENT_KEY);
  return token && token.trim() ? token.trim() : null;
}

export function previewEmbedPath(
  publicId: string,
  token: string,
  lang: "sv" | "en" = "sv"
): string {
  const prefix = lang === "en" ? "/en" : "";
  return `${prefix}/embed/${encodeURIComponent(publicId)}?${PREVIEW_QUERY}=1#${FRAGMENT_KEY}=${encodeURIComponent(token)}`;
}
