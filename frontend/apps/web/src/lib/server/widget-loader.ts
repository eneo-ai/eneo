/**
 * The built widget loader (`packages/widget-loader/dist`) as served from
 * `/widget/<version>/eneo.js` and described by the admin snippet.
 *
 * Vite inlines the bundle and its manifest into the server build, so the
 * runner image needs neither the package nor its node_modules. When the
 * package has not been built the globs are empty and the route answers 503.
 */

type Manifest = {
  version: string;
  channel: string;
  file: string;
  integrity: string;
  bytes: number;
  gzip_bytes: number;
};

export type WidgetLoaderBundle = {
  version: string;
  /** Floating alias hosts embed by default, e.g. `v1`; set by the package, not its version. */
  channel: string;
  integrity: string;
  source: string;
};

const sources = import.meta.glob("../../../../../packages/widget-loader/dist/eneo.js", {
  query: "?raw",
  import: "default"
}) as Record<string, () => Promise<string>>;

const manifests = import.meta.glob("../../../../../packages/widget-loader/dist/manifest.json", {
  query: "?raw",
  import: "default"
}) as Record<string, () => Promise<string>>;

let cached: Promise<WidgetLoaderBundle | null> | undefined;

/** The release a built manifest describes; a build from before the channel was recorded counts as not built. */
export function readManifest(raw: string): Omit<WidgetLoaderBundle, "source"> | null {
  const parsed = JSON.parse(raw) as Partial<Manifest>;
  if (!parsed.version || !parsed.channel || !parsed.integrity) return null;
  return { version: parsed.version, channel: parsed.channel, integrity: parsed.integrity };
}

async function load(): Promise<WidgetLoaderBundle | null> {
  const [source] = Object.values(sources);
  const [manifest] = Object.values(manifests);
  if (!source || !manifest) return null;
  const release = readManifest(await manifest());
  return release ? { ...release, source: await source() } : null;
}

export function getWidgetLoaderBundle(): Promise<WidgetLoaderBundle | null> {
  if (import.meta.env.DEV) return load();
  cached ??= load();
  return cached;
}

/**
 * Which URL variant a request asks for: the floating channel (`v1`), the
 * exact built version (pinned, immutable) or nothing we serve.
 */
export function resolveLoaderVariant(
  bundle: WidgetLoaderBundle,
  requested: string
): "channel" | "pinned" | null {
  if (requested === bundle.channel) return "channel";
  if (requested === bundle.version) return "pinned";
  return null;
}
