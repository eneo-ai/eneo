import data from "../releases.json";

/** @type {import("./index").Release[]} */
export const releases = data.releases;

export function latestRelease() {
  return releases[0];
}

/** @param {string | null | undefined} seenVersion */
export function hasUnseenRelease(seenVersion) {
  const latest = latestRelease();
  if (!latest) return false;
  return latest.version !== seenVersion;
}

/**
 * @param {import("./index").Release} release
 * @param {boolean} isAdmin
 */
export function visibleEntries(release, isAdmin) {
  return release.entries.filter((entry) => isAdmin || (entry.audience ?? "all") === "all");
}
