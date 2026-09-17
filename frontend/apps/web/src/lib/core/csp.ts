/**
 * Frame policy for responses.
 *
 * The app is never framed except by the widget embed page, which sets
 * `locals.frameAncestors` to the widget's allowed origins. Everything else
 * gets `frame-ancestors 'none'` plus `X-Frame-Options: DENY` for browsers
 * that predate CSP level 2.
 */

export const EMBED_ROUTE_PREFIX = "/(public)/embed";

const FRAME_DIRECTIVE = "frame-ancestors";
const WORKER_DIRECTIVE = "worker-src";

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
  options: { frameAncestors: string; allowBlobWorkers?: boolean }
): string {
  const directives = parse(csp);
  directives.set(FRAME_DIRECTIVE, options.frameAncestors);
  if (options.allowBlobWorkers) {
    // The ALTCHA proof-of-work widget spawns its workers from blob: URLs.
    directives.set(WORKER_DIRECTIVE, "'self' blob:");
  }
  return serialize(directives);
}

/** CSP `frame-ancestors` value for a list of host sources; empty list denies. */
export function frameAncestorsFor(sources: readonly string[]): string {
  const cleaned = sources.map((source) => source.trim()).filter(Boolean);
  return cleaned.length > 0 ? `'self' ${cleaned.join(" ")}` : "'none'";
}
