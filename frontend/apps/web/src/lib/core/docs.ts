import { latestRelease, releases, type Release } from "@eneo/whats-new";

/**
 * The docs version this build is documented in: its release line once that
 * release is dated in releases.json (`/v2.3`), otherwise `/dev`, which follows
 * unreleased work. The unversioned site follows the latest stable line, which
 * has no pages for features that shipped after it.
 */
export function docsVersionPath(release: Pick<Release, "version" | "date"> | undefined): string {
  const line = release?.date ? /^(\d+)\.(\d+)\./.exec(release.version) : null;
  return line ? `/v${line[1]}.${line[2]}` : "/dev";
}

/** Pages the app links before their release ships, by the What's new entry that documents them. */
const INTRODUCED_BY = {
  "guides/embed-widget": "web-widgets",
  "guides/oidc-federation/single-tenant": "admin-sign-in-settings"
} as const;

type DocsPage = "guides/object-content-storage" | keyof typeof INTRODUCED_BY;

/** Public docs keep English at existing URLs; Swedish is a sibling route. */
export function docsUrl(page: DocsPage, locale: string, anchor?: string): string {
  const languagePrefix = locale === "sv" ? "/sv" : "";
  const entryId = page in INTRODUCED_BY ? INTRODUCED_BY[page as keyof typeof INTRODUCED_BY] : null;
  const release = entryId
    ? releases.find((release) => release.entries.some((entry) => entry.id === entryId))
    : latestRelease();
  const version = docsVersionPath(release);
  return `https://docs.eneo.ai${version}${languagePrefix}/${page}${anchor ? `#${anchor}` : ""}`;
}
