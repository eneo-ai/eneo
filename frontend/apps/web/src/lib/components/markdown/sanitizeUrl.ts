/**
 * URL-scheme allowlists for rendered Markdown.
 *
 * Markdown can carry untrusted content (e.g. MCP tool output from a third-party
 * server). `marked` does not block dangerous URL schemes, so `[x](javascript:…)`
 * or `![](vbscript:…)` would otherwise reach the DOM with a live, script-bearing
 * href/src. These helpers gate the href/src on a scheme allowlist before it is
 * bound by the Link/Image renderers.
 */

// Browsers strip ASCII tab/newline/CR from URLs and ignore leading control
// characters, so a scheme can be hidden as `java\nscript:` or `  javascript:`.
// Normalize the same way (drop every C0 control char and space, then lowercase)
// before reading the scheme so those obfuscations can't slip past the allowlist.
// Done char-by-char to keep the source free of literal control bytes.
function normalizeForSchemeCheck(url: string): string {
  let stripped = "";
  for (let i = 0; i < url.length; i++) {
    if (url.charCodeAt(i) > 0x20) stripped += url[i];
  }
  return stripped.toLowerCase();
}

const SCHEME_RE = /^([a-z][a-z0-9+.-]*):/;

const SAFE_LINK_SCHEMES = new Set(["http", "https", "mailto", "tel"]);

/**
 * Returns `href` when it is safe to navigate to, otherwise `undefined`.
 *
 * Scheme-less URLs (relative paths, `#anchor`, protocol-relative `//host`) carry
 * no scheme to abuse and are passed through. The original string is returned
 * unchanged when safe; the browser normalizes any residual control chars itself.
 */
export function sanitizeLinkHref(href: string | null | undefined): string | undefined {
  if (!href) return undefined;
  const match = SCHEME_RE.exec(normalizeForSchemeCheck(href));
  if (!match) return href;
  return SAFE_LINK_SCHEMES.has(match[1]) ? href : undefined;
}

/**
 * Returns `src` when it is safe for an `<img>`, otherwise `undefined`.
 *
 * Allows http(s) and image-only `data:` URIs; blocks `javascript:`, non-image
 * `data:` (e.g. `data:text/html`), and every other scheme.
 */
export function sanitizeImageSrc(src: string | null | undefined): string | undefined {
  if (!src) return undefined;
  const normalized = normalizeForSchemeCheck(src);
  const match = SCHEME_RE.exec(normalized);
  if (!match) return src;
  if (match[1] === "data") {
    return /^data:image\//.test(normalized) ? src : undefined;
  }
  return match[1] === "http" || match[1] === "https" ? src : undefined;
}
