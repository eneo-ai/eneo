// Browsers strip ASCII tab/newline/CR from URLs and ignore leading control
// characters, so a scheme can be hidden as `java\nscript:` or `  javascript:`.
// Normalise the same way (drop every C0 control char and space, then lowercase)
// before reading the scheme so those obfuscations can't slip past the allowlist.
function normalizeForSchemeCheck(url: string): string {
  let stripped = "";
  for (let i = 0; i < url.length; i++) {
    if (url.charCodeAt(i) > 0x20) stripped += url[i];
  }
  return stripped.toLowerCase();
}

const SCHEME = /^([a-z][a-z0-9+.-]*):/;

/**
 * `src` when it is safe for an `<img>`, otherwise undefined: http(s) and
 * image-only `data:` URIs pass; `javascript:`, non-image `data:` and every
 * other scheme do not. A document is the model's writing, which a third-party
 * tool may have shaped.
 */
export function sanitizeImageSrc(src: string | null | undefined): string | undefined {
  if (!src) return undefined;
  const normalized = normalizeForSchemeCheck(src);
  const match = SCHEME.exec(normalized);
  if (!match) return src;
  if (match[1] === "data") return /^data:image\//.test(normalized) ? src : undefined;
  return match[1] === "http" || match[1] === "https" ? src : undefined;
}
