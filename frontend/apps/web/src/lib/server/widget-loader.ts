/**
 * Widget loader assets as served from `/widget/<version>/`. The current
 * package build lives in dist/; older pinned releases are checked-in byte
 * snapshots under releases/. Vite embeds both in the server build, so the
 * runner image needs neither package directory at runtime.
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

type RawFile = () => Promise<string>;

const sources = import.meta.glob("../../../../../packages/widget-loader/dist/eneo.js", {
  query: "?raw",
  import: "default"
}) as Record<string, RawFile>;
const styles = import.meta.glob("../../../../../packages/widget-loader/dist/eneo.css", {
  query: "?raw",
  import: "default"
}) as Record<string, RawFile>;
const manifests = import.meta.glob("../../../../../packages/widget-loader/dist/manifest.json", {
  query: "?raw",
  import: "default"
}) as Record<string, RawFile>;

const archivedSources = import.meta.glob(
  "../../../../../packages/widget-loader/releases/*/eneo.js",
  { query: "?raw", import: "default" }
) as Record<string, RawFile>;
const archivedStyles = import.meta.glob(
  "../../../../../packages/widget-loader/releases/*/eneo.css",
  { query: "?raw", import: "default" }
) as Record<string, RawFile>;
const archivedManifests = import.meta.glob(
  "../../../../../packages/widget-loader/releases/*/manifest.json",
  { query: "?raw", import: "default" }
) as Record<string, RawFile>;

let cachedCurrent: Promise<WidgetLoaderBundle | null> | undefined;
const cachedArchives = new Map<string, Promise<WidgetLoaderBundle | null>>();

/** An old manifest has no CSS because its loader carried an inline stylesheet. */
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

async function loadBundle(
  manifest: RawFile | undefined,
  source: RawFile | undefined,
  css: RawFile | undefined
): Promise<WidgetLoaderBundle | null> {
  if (!manifest || !source) return null;
  const release = readManifest(await manifest());
  if (!release || (release.cssIntegrity && !css)) return null;
  return {
    ...release,
    source: await source(),
    ...(release.cssIntegrity && css ? { cssSource: await css() } : {})
  };
}

function current(): Promise<WidgetLoaderBundle | null> {
  const load = () =>
    loadBundle(Object.values(manifests)[0], Object.values(sources)[0], Object.values(styles)[0]);
  if (import.meta.env.DEV) return load();
  cachedCurrent ??= load();
  return cachedCurrent;
}

function archived(version: string): Promise<WidgetLoaderBundle | null> {
  // Match a known build-time path. The request cannot be used as a filesystem
  // path, and an arbitrary version cannot make the server fetch a new file.
  const manifestPath = Object.keys(archivedManifests).find((path) =>
    path.endsWith(`/releases/${version}/manifest.json`)
  );
  if (!manifestPath) return Promise.resolve(null);
  const assetRoot = manifestPath.slice(0, -"manifest.json".length);
  const load = async () => {
    const bundle = await loadBundle(
      archivedManifests[manifestPath],
      archivedSources[`${assetRoot}eneo.js`],
      archivedStyles[`${assetRoot}eneo.css`]
    );
    return bundle?.version === version ? bundle : null;
  };
  if (import.meta.env.DEV) return load();
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
