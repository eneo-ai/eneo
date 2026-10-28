/**
 * Where an item or document lives at its source (SharePoint, Confluence), when
 * it is safe to link to: an absolute https URL without credentials. Anything
 * else (another scheme, a relative or malformed address, none) is null, and the
 * caller renders no link. The backend imports an item only with an https
 * address or none, and serves an item's or document's address as null unless
 * it is https; this is the second wall.
 */
export function safeExternalUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:" || parsed.username || parsed.password) return null;
  return parsed.href;
}
