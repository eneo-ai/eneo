/**
 * URL-scheme allowlists for an `href`/`src` taken from content a third-party
 * server may have shaped: chat Markdown, sources and citations, MCP references and
 * images, links in a .docx preview and image sources in the document editor.
 * Keep the allowed content schemes consistent across renderers instead of
 * relying on their different defaults. Streamdown also sanitizes Markdown HTML
 * (components/ai-elements/answer-markdown.ts), and editor links use
 * `isAllowedHref` (workspace/preview/editor/extensions.ts). Ported from the
 * web app's `markdown/sanitizeUrl.ts`; keep the two alike.
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
  return SAFE_LINK_SCHEMES.has(match[1]!) ? href : undefined;
}

/**
 * Returns `href` when it is an absolute http(s) URL, otherwise `undefined`.
 *
 * For an address stored with content, such as a cited document's source url:
 * it links out to the source, so unlike a Markdown link it has no reason to be
 * relative or a mail or phone link, and whoever stored it chose the value.
 */
export function sanitizeWebHref(href: string | null | undefined): string | undefined {
  // Require an authority in the original string: `https:settings` and
  // `https:/settings` otherwise resolve relative to the current HTTPS page.
  // Removing spaces/control characters here could also approve a different URL.
  if (!href || !/^https?:\/\//i.test(href)) return undefined;
  try {
    // The prefix alone does not reject a missing/invalid host or an invalid port.
    new URL(href);
    return href;
  } catch {
    return undefined;
  }
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
