import { latestRelease, type Release } from "@eneo/whats-new";

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

/** Public docs keep English at existing URLs; Swedish is a sibling route. */
export function docsUrl(
  page: "guides/object-content-storage" | "guides/embed-widget" | "guides/space-oversight",
  locale: string,
  anchor?: string
): string {
  const languagePrefix = locale === "sv" ? "/sv" : "";
  const version = docsVersionPath(latestRelease());
  return `https://docs.eneo.ai${version}${languagePrefix}/${page}${anchor ? `#${anchor}` : ""}`;
}
