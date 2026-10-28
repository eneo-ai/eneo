import type { WidgetPublicConfig } from "@eneo/eneo-js";
import { embedLocale } from "../embed-language";
import { PREVIEW_QUERY } from "../preview";
import type { Locale } from "@/lib/i18n/locales";
import { fetchPublicConfig } from "./public-config";

/**
 * What the response headers of an embed page depend on, decided before the
 * page renders (src/proxy.ts): where the page may be framed, which images
 * it may show, and the language and colour scheme its document starts in.
 * Mirrors the SvelteKit embed load (apps/web … embed/[publicId]/+page.server.ts).
 */

export type EmbedScheme = "light" | "dark" | "system";

/** The request headers src/proxy.ts sets for the root layout to read. */
export const EMBED_LOCALE_HEADER = "x-eneo-embed-locale";
export const EMBED_SCHEME_HEADER = "x-eneo-embed-scheme";

export function parseEmbedScheme(raw: string | null | undefined): EmbedScheme {
  return raw === "light" || raw === "dark" ? raw : "system";
}

export type EmbedPolicy = {
  /** CSP `frame-ancestors` value. */
  frameAncestors: string;
  /** Image origins on top of the page's own. */
  imgSources: string[];
  locale: Locale;
  scheme: EmbedScheme;
};

/**
 * A CSP host source: optional scheme, a DNS name (with an optional `*.`
 * wildcard) or IP literal, optional port. The backend validates allowed
 * origins the same way; this is the last line before the header, so anything
 * else (directive separators, spaces) is dropped rather than emitted.
 */
const HOST_SOURCE =
  /^(?:https?:\/\/)?(?:(?:\*\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*|\[[0-9a-f:.]+\])(?::(?:\d{1,5}|\*))?$/i;

export function isHostSource(source: string): boolean {
  return HOST_SOURCE.test(source);
}

/** A bare scheme source (`https:`), which CSP accepts as "anything over that scheme". */
const SCHEME_SOURCE = /^https?:$/i;

export function hostSources(sources: readonly string[] | undefined): string[] {
  const cleaned = (sources ?? [])
    .map((source) => source.trim())
    .filter((source) => isHostSource(source) || SCHEME_SOURCE.test(source));
  return [...new Set(cleaned)];
}

/** CSP `frame-ancestors` value for a list of host sources; empty or all-invalid denies. */
export function frameAncestorsFor(sources: readonly string[]): string {
  const cleaned = hostSources(sources);
  return cleaned.length > 0 ? `'self' ${cleaned.join(" ")}` : "'none'";
}

/** The origin of an absolute URL as a CSP source, or null when it has none. */
export function originSource(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const origin = new URL(url).origin;
    return origin !== "null" && isHostSource(origin) ? origin : null;
  } catch {
    return null;
  }
}

export function parseScheme(raw: string | null): "light" | "dark" | "auto" | null {
  return raw === "light" || raw === "dark" || raw === "auto" ? raw : null;
}

/** `/embed/<id>` or `/en/embed/<id>`: the widget and the language of the path. */
export function parseEmbedPath(pathname: string): { publicId: string; pathLocale: Locale } | null {
  const match = /^(\/en)?\/embed\/([^/]+)$/.exec(pathname);
  if (!match) return null;
  return { publicId: decodeURIComponent(match[2]!), pathLocale: match[1] ? "en" : "sv" };
}

type Cached = { expires: number; config: WidgetPublicConfig | null };

// The page fetches the configuration again for what it shows (never cached,
// so a pause reaches the next view); the headers may lag it by this much.
// Allowed origins and the pinned language or scheme change rarely, and a
// stale policy for a paused widget frames a notice that protects nothing.
const POLICY_TTL_MS = 30_000;
const policyCache = new Map<string, Cached>();

async function cachedConfig(
  publicId: string,
  now: number,
  fetchConfig: typeof fetchPublicConfig
): Promise<WidgetPublicConfig | null> {
  const cached = policyCache.get(publicId);
  if (cached && cached.expires > now) return cached.config;
  const config = await fetchConfig(publicId);
  policyCache.set(publicId, { expires: now + POLICY_TTL_MS, config });
  return config;
}

/** Test-only: forget cached policies. */
export function resetEmbedPolicyCache(): void {
  policyCache.clear();
}

export async function embedPolicy(
  { publicId, pathLocale }: { publicId: string; pathLocale: Locale },
  search: URLSearchParams,
  options: { now?: number; fetchConfig?: typeof fetchPublicConfig } = {}
): Promise<EmbedPolicy> {
  // The admin page's live preview: the token is in the fragment, so the
  // configuration is fetched in the browser and only Eneo itself may frame it.
  const preview = search.get(PREVIEW_QUERY) === "1";
  const standalone = search.get("mode") === "full";
  const hostScheme = parseScheme(search.get("scheme"));

  let config: WidgetPublicConfig | null = null;
  let failed = false;
  if (!preview) {
    try {
      config = await cachedConfig(
        publicId,
        options.now ?? Date.now(),
        options.fetchConfig ?? fetchPublicConfig
      );
    } catch {
      // A backend restart or timeout: the error page may be framed too, or
      // the loader keeps a refused, blank panel until the host page reloads.
      failed = true;
    }
  }

  // The browser enforces where this page may render. The stand-alone page has
  // no reason to be framed at all; the notice for a paused, archived or
  // unknown widget carries nothing worth protecting and the allowed origins
  // are unknown for it, so any site may frame it.
  const frameAncestors =
    failed || (!preview && !config)
      ? "*"
      : preview || standalone || !config
        ? "'self'"
        : frameAncestorsFor(config.frame_ancestors);

  // The page shows the organisation's logo from its own host, at most;
  // answer Markdown must not be able to reach anything else (an injected
  // image URL would ship the visitor's question to a third party). The
  // preview has no configuration yet, so it accepts any https image.
  const logoOrigin = originSource(config?.theme.logo_url);
  const imgSources = preview ? ["https:"] : logoOrigin ? [logoOrigin] : [];

  const pinned = config?.theme.color_scheme;
  const scheme: EmbedScheme =
    pinned === "light" || pinned === "dark"
      ? pinned
      : hostScheme === "light" || hostScheme === "dark"
        ? hostScheme
        : "system";

  return {
    frameAncestors,
    imgSources,
    locale: embedLocale(pathLocale, config?.language ?? "auto"),
    scheme
  };
}
