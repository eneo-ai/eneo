// @ts-check
/**
 * @typedef {{version: string, channel: string, integrity: string}} LoaderRelease
 * @typedef {{origin: string, publicId: string, language?: "sv" | "en" | "auto",
 *   release: LoaderRelease | null}} SnippetOptions
 */
/**
 * The install snippets the admin page shows. The floating channel (`v1`)
 * follows Eneo releases and is the default; the pinned variant carries the
 * SRI hash of the exact loader build for hosts that require `integrity`.
 * Neither exists without a loader build: it would point at an address this
 * installation answers with 503.
 *
 * Neither carries a setting the editor can change later: the loader reads
 * the saved language, position and colours from Eneo on every page, so an
 * edit or a template publication reaches sites without a new snippet.
 */
const escapeAttribute = /** @param {string} value */ (value) =>
  value.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
/** @param {Array<[string, string]>} attributes
 * @returns {string} */
function scriptTag(attributes) {
  const rendered = attributes.map(([name, value]) => `${name}="${escapeAttribute(value)}"`);
  return `<script async ${rendered.join(" ")}></script>`;
}
/** @param {string} origin
 * @param {string} version
 * @returns {string} */
export function loaderUrl(origin, version) {
  return `${origin.replace(/\/+$/, "")}/widget/${version}/eneo.js`;
}
/** Floating snippet; updates with every Eneo release.
 * @param {SnippetOptions} options
 * @returns {string | null} */
export function floatingSnippet(options) {
  if (!options.release) return null;
  return scriptTag([
    ["src", loaderUrl(options.origin, options.release.channel)],
    ["data-widget-id", options.publicId]
  ]);
}
/** Pinned snippet with Subresource Integrity; the host replaces it when the loader version changes.
 * @param {SnippetOptions} options
 * @returns {string | null} */
export function pinnedSnippet(options) {
  if (!options.release) return null;
  return scriptTag([
    ["src", loaderUrl(options.origin, options.release.version)],
    ["integrity", options.release.integrity],
    ["crossorigin", "anonymous"],
    ["data-widget-id", options.publicId]
  ]);
}
/**
 * The full-page chat, for linking from a site that cannot run scripts. The
 * page moves to the widget's language itself if it changes after copying.
 *
 * @param {Pick<SnippetOptions, "origin" | "publicId" | "language">} options
 * @returns {string} */
export function standaloneUrl(options) {
  const prefix = options.language === "en" ? "/en" : "";
  return `${options.origin.replace(/\/+$/, "")}${prefix}/embed/${encodeURIComponent(options.publicId)}?mode=full`;
}
