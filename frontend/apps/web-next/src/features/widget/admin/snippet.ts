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

export type LoaderRelease = {
  version: string;
  channel: string;
  integrity: string;
};

export type SnippetOptions = {
  /** Public origin of this Eneo installation, e.g. `https://eneo.kommun.se`. */
  origin: string;
  publicId: string;
  /** Widget language when it is fixed; `auto` follows the host page. Only the stand-alone link uses it. */
  language?: "sv" | "en" | "auto";
  release: LoaderRelease | null;
};

const escapeAttribute = (value: string) => value.replace(/&/g, "&amp;").replace(/"/g, "&quot;");

function scriptTag(attributes: Array<[string, string]>): string {
  const rendered = attributes.map(([name, value]) => `${name}="${escapeAttribute(value)}"`);
  return `<script async ${rendered.join(" ")}></script>`;
}

export function loaderUrl(origin: string, version: string): string {
  return `${origin.replace(/\/+$/, "")}/widget/${version}/eneo.js`;
}

/** Floating snippet; updates with every Eneo release. */
export function floatingSnippet(options: SnippetOptions): string | null {
  if (!options.release) return null;
  return scriptTag([
    ["src", loaderUrl(options.origin, options.release.channel)],
    ["data-widget-id", options.publicId]
  ]);
}

/** Pinned snippet with Subresource Integrity; the host replaces it when the loader version changes. */
export function pinnedSnippet(options: SnippetOptions): string | null {
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
 */
export function standaloneUrl(
  options: Pick<SnippetOptions, "origin" | "publicId" | "language">
): string {
  const prefix = options.language === "en" ? "/en" : "";
  return `${options.origin.replace(/\/+$/, "")}${prefix}/embed/${encodeURIComponent(options.publicId)}?mode=full`;
}
