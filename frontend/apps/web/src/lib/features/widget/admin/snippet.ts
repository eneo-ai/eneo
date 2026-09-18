/**
 * The install snippets the admin page shows. Floating `v1` follows Eneo
 * releases and is the default; the pinned variant carries the SRI hash of
 * the exact loader build for hosts that require `integrity`.
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
  /** Widget language when it is fixed; `auto` follows the host page. */
  language?: "sv" | "en" | "auto";
  /** Launcher placement as saved in the editor; the loader defaults to bottom-right. */
  position?: "bottom-right" | "bottom-left";
  release: LoaderRelease | null;
};

const escapeAttribute = (value: string) => value.replace(/&/g, "&amp;").replace(/"/g, "&quot;");

function scriptTag(attributes: Array<[string, string]>): string {
  const rendered = attributes.map(([name, value]) => `${name}="${escapeAttribute(value)}"`);
  return `<script async ${rendered.join(" ")}></script>`;
}

function languageAttribute(language: SnippetOptions["language"]): Array<[string, string]> {
  return language && language !== "auto" ? [["data-lang", language]] : [];
}

function positionAttribute(position: SnippetOptions["position"]): Array<[string, string]> {
  return position ? [["data-position", position]] : [];
}

export function loaderUrl(origin: string, version: string): string {
  return `${origin.replace(/\/+$/, "")}/widget/${version}/eneo.js`;
}

/** Floating snippet; updates with every Eneo release. */
export function floatingSnippet(options: SnippetOptions): string {
  const channel = options.release?.channel ?? "v1";
  return scriptTag([
    ["src", loaderUrl(options.origin, channel)],
    ["data-widget-id", options.publicId],
    ...languageAttribute(options.language),
    ...positionAttribute(options.position)
  ]);
}

/** Pinned snippet with Subresource Integrity; must be updated by the host on each release. */
export function pinnedSnippet(options: SnippetOptions): string | null {
  if (!options.release) return null;
  return scriptTag([
    ["src", loaderUrl(options.origin, options.release.version)],
    ["integrity", options.release.integrity],
    ["crossorigin", "anonymous"],
    ["data-widget-id", options.publicId],
    ...languageAttribute(options.language),
    ...positionAttribute(options.position)
  ]);
}

/** The full-page chat, for linking from a site that cannot run scripts. */
export function standaloneUrl(
  options: Pick<SnippetOptions, "origin" | "publicId" | "language">
): string {
  const prefix = options.language === "en" ? "/en" : "";
  return `${options.origin.replace(/\/+$/, "")}${prefix}/embed/${encodeURIComponent(options.publicId)}?mode=full`;
}
