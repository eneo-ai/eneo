import { readFile } from "node:fs/promises";
import path from "node:path";

/**
 * Widget loader assets as served from `/widget/<version>/`. The current
 * package build lives in packages/widget-loader/dist; older pinned releases
 * are checked-in byte snapshots under releases/. Both are read from disk:
 * next.config.ts traces them into the standalone output, and the image
 * builds the package before the app (Dockerfile).
 *
 * Paths are resolved from the working directory, which is the app directory
 * both in development and in the standalone server (its entry point changes
 * to its own directory before it starts).
 */

type Manifest = {
  version: string;
  channel: string;
  file: string;
  integrity: string;
  bytes: number;
  gzip_bytes: number;
  css_file?: string;
  css_integrity?: string;
  css_bytes?: number;
};

export type WidgetLoaderBundle = {
  version: string;
  /** Floating alias hosts embed by default, e.g. `v1`. */
  channel: string;
  integrity: string;
  source: string;
  cssIntegrity?: string;
  cssSource?: string;
};

const PACKAGE_DIR = path.resolve(process.cwd(), "..", "..", "packages", "widget-loader");
/** An archived release directory is named by its exact version; nothing else is read. */
const VERSION = /^\d+\.\d+\.\d+$/;

let cachedCurrent: Promise<WidgetLoaderBundle | null> | undefined;
const cachedArchives = new Map<string, Promise<WidgetLoaderBundle | null>>();

/** A manifest without CSS belongs to a loader that carries its stylesheet inline. */
export function readManifest(raw: string): Omit<WidgetLoaderBundle, "source" | "cssSource"> | null {
  const parsed = JSON.parse(raw) as Partial<Manifest>;
  if (!parsed.version || !parsed.channel || !parsed.integrity || parsed.file !== "eneo.js") {
    return null;
  }
  if (
    (parsed.css_file || parsed.css_integrity) &&
    (parsed.css_file !== "eneo.css" || !parsed.css_integrity)
  ) {
    return null;
  }
  return {
    version: parsed.version,
    channel: parsed.channel,
    integrity: parsed.integrity,
    ...(parsed.css_integrity ? { cssIntegrity: parsed.css_integrity } : {})
  };
}

async function readOptional(file: string): Promise<string | null> {
  try {
    return await readFile(file, "utf8");
  } catch {
    return null;
  }
}

async function loadBundle(dir: string): Promise<WidgetLoaderBundle | null> {
  const manifest = await readOptional(path.join(dir, "manifest.json"));
  if (!manifest) return null;
  let release: ReturnType<typeof readManifest>;
  try {
    release = readManifest(manifest);
  } catch {
    return null;
  }
  if (!release) return null;
  const source = await readOptional(path.join(dir, "eneo.js"));
  if (!source) return null;
  const css = release.cssIntegrity ? await readOptional(path.join(dir, "eneo.css")) : null;
  if (release.cssIntegrity && !css) return null;
  return { ...release, source, ...(css ? { cssSource: css } : {}) };
}

function current(): Promise<WidgetLoaderBundle | null> {
  const load = () => loadBundle(path.join(PACKAGE_DIR, "dist"));
  if (process.env.NODE_ENV !== "production") return load();
  cachedCurrent ??= load();
  return cachedCurrent;
}

function archived(version: string): Promise<WidgetLoaderBundle | null> {
  // The request never becomes a path: only an exact version of a checked-in
  // release directory is read, and its manifest must say the same version.
  if (!VERSION.test(version)) return Promise.resolve(null);
  const load = async () => {
    const bundle = await loadBundle(path.join(PACKAGE_DIR, "releases", version));
    return bundle?.version === version ? bundle : null;
  };
  if (process.env.NODE_ENV !== "production") return load();
  let result = cachedArchives.get(version);
  if (!result) {
    result = load();
    cachedArchives.set(version, result);
  }
  return result;
}

/** Current release for admin snippets, or exact archived release for a pinned URL. */
export async function getWidgetLoaderBundle(
  requested?: string
): Promise<WidgetLoaderBundle | null> {
  if (!requested) return current();
  const latest = await current();
  if (latest && (requested === latest.channel || requested === latest.version)) return latest;
  return archived(requested);
}

/** The channel follows releases; each exact version is immutable. */
export function resolveLoaderVariant(
  bundle: WidgetLoaderBundle,
  requested: string
): "channel" | "pinned" | null {
  if (requested === bundle.channel) return "channel";
  if (requested === bundle.version) return "pinned";
  return null;
}

const CHANNEL_CACHE = "public, max-age=3600";
const PINNED_CACHE = "public, max-age=31536000, immutable";

/**
 * `GET /widget/v1/eneo.js` and `eneo.css`: the script host sites include
 * and the external stylesheet for hosts whose CSP disallows inline CSS. The
 * floating channel follows releases; the pinned `/widget/1.2.3/eneo.js`
 * never changes and carries the SRI hash printed by the admin snippet. CORS
 * is open on purpose: `integrity` only works on scripts fetched with
 * `crossorigin`.
 */
export async function loaderAssetResponse(
  request: Request,
  version: string,
  asset: "js" | "css"
): Promise<Response> {
  const latest = await getWidgetLoaderBundle();
  if (!latest) {
    // The package has not been built; see packages/widget-loader/README.md.
    return new Response(null, { status: 503, headers: { "retry-after": "60" } });
  }
  const bundle = await getWidgetLoaderBundle(version);
  const variant = bundle ? resolveLoaderVariant(bundle, version) : null;
  if (!bundle || !variant) return new Response(null, { status: 404 });
  const body = asset === "js" ? bundle.source : bundle.cssSource;
  const integrity = asset === "js" ? bundle.integrity : bundle.cssIntegrity;
  if (!body || !integrity) return new Response(null, { status: 404 });

  const etag = `"${integrity}"`;
  const headers: Record<string, string> = {
    "cache-control": variant === "pinned" ? PINNED_CACHE : CHANNEL_CACHE,
    "access-control-allow-origin": "*",
    "cross-origin-resource-policy": "cross-origin",
    "x-content-type-options": "nosniff",
    "x-eneo-widget-version": bundle.version,
    etag
  };
  if (request.headers.get("if-none-match") === etag) {
    return new Response(null, { status: 304, headers });
  }
  return new Response(body, {
    headers: {
      ...headers,
      "content-type": asset === "js" ? "text/javascript; charset=utf-8" : "text/css; charset=utf-8"
    }
  });
}
