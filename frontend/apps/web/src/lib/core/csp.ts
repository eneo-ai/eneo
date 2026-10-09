/**
 * Frame policy for responses.
 *
 * The app is never framed except by the widget embed page, which sets
 * `locals.frameAncestors` to the widget's allowed origins. Everything else
 * gets `frame-ancestors 'none'` plus `X-Frame-Options: DENY` for browsers
 * that predate CSP level 2.
 */

export const EMBED_ROUTE_PREFIX = "/(public)/embed";
export const WIDGET_LOADER_ROUTE_PREFIX = "/(public)/widget";

const FRAME_DIRECTIVE = "frame-ancestors";
const WORKER_DIRECTIVE = "worker-src";
const IMG_DIRECTIVE = "img-src";
const CONNECT_DIRECTIVE = "connect-src";

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

function hostSources(sources: readonly string[] | undefined): string[] {
  const cleaned = (sources ?? [])
    .map((source) => source.trim())
    .filter((source) => isHostSource(source) || SCHEME_SOURCE.test(source));
  return [...new Set(cleaned)];
}

/**
 * Directives the embed page adds on top of SvelteKit's nonce-based script-src.
 * `style-src` is deliberately not restricted: server-rendered `style:`
 * attributes and the ALTCHA widget's shadow-root styles are inline, and a
 * nonce cannot reach either without patching both.
 */
export const EMBED_HARDENING: ReadonlyArray<readonly [string, string]> = [
  ["base-uri", "'none'"],
  ["object-src", "'none'"],
  ["form-action", "'self'"],
  ["frame-src", "'none'"]
];

function parse(csp: string | null | undefined): Map<string, string> {
  const directives = new Map<string, string>();
  for (const part of (csp ?? "").split(";")) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const [name, ...values] = trimmed.split(/\s+/);
    directives.set(name.toLowerCase(), values.join(" "));
  }
  return directives;
}

function serialize(directives: Map<string, string>): string {
  return [...directives.entries()]
    .map(([name, value]) => (value ? `${name} ${value}` : name))
    .join("; ");
}

/**
 * Merge a frame policy into an existing CSP header value. Other directives
 * (SvelteKit's nonce-based `script-src`, …) are kept verbatim.
 */
export function withFramePolicy(
  csp: string | null | undefined,
  options: {
    frameAncestors: string;
    allowBlobWorkers?: boolean;
    harden?: boolean;
    /**
     * Where the embed page may load images from and connect to, on top of
     * `'self'`. Answer Markdown can carry any `<img src>`, so without this an
     * injected image URL would ship the visitor's question to a third party.
     */
    embedSources?: { img?: readonly string[]; connect?: readonly string[] };
  }
): string {
  const directives = parse(csp);
  directives.set(FRAME_DIRECTIVE, options.frameAncestors);
  if (options.allowBlobWorkers) {
    // The ALTCHA proof-of-work widget spawns its workers from blob: URLs.
    directives.set(WORKER_DIRECTIVE, "'self' blob:");
  }
  if (options.embedSources) {
    directives.set(
      IMG_DIRECTIVE,
      ["'self'", "data:", "blob:", ...hostSources(options.embedSources.img)].join(" ")
    );
    directives.set(
      CONNECT_DIRECTIVE,
      ["'self'", ...hostSources(options.embedSources.connect)].join(" ")
    );
  }
  if (options.harden) {
    for (const [name, value] of EMBED_HARDENING) {
      if (!directives.has(name)) directives.set(name, value);
    }
  }
  return serialize(directives);
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
