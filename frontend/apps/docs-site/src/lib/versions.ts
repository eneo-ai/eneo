// Version metadata is injected at build time by scripts/build-versions.mjs.
// A plain `bun run dev`/`bun run build` has no versions and renders a single-version site.
export type DocsVersionKind = "stable" | "archive" | "dev";

export interface DocsVersion {
  id: string;
  label: string;
  kind: DocsVersionKind;
  basePath: string;
  gitRef: string;
  tag?: string;
}

export function getDocsVersions(): DocsVersion[] {
  try {
    return JSON.parse(process.env.NEXT_PUBLIC_DOCS_VERSIONS || "[]");
  } catch {
    return [];
  }
}

export function getCurrentDocsVersion(): DocsVersion | undefined {
  const id = process.env.NEXT_PUBLIC_DOCS_VERSION;
  return getDocsVersions().find((version) => version.id === id);
}

export function getStableDocsVersion(): DocsVersion | undefined {
  return getDocsVersions().find((version) => version.kind === "stable");
}

export function versionTitle(version: DocsVersion): string {
  switch (version.kind) {
    case "stable":
      return `${version.label} (latest)`;
    case "dev":
      return "dev (unreleased)";
    default:
      return version.label;
  }
}
