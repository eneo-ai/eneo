import { compareVersions, visibleEntries } from "@eneo/whats-new";
import type { PermissionCheck, EntryArea, Release, ReleaseEntry } from "@eneo/whats-new";

export interface WhatsNewFilters {
  /** `null` = every area. */
  area: EntryArea | null;
  /** Only entries with a Show me target. */
  showMeOnly: boolean;
}

/**
 * "Read" is decided against the seen marker as it was when the page opened,
 * not the one the visit itself writes — otherwise everything would count as
 * read the moment the page loads.
 */
export function isReadRelease(release: Release, seenAtOpen: string | null): boolean {
  if (!seenAtOpen) return false;
  return compareVersions(release.version, seenAtOpen) <= 0;
}

/** Entries of one release this user may see, narrowed by the filters. */
export function filterEntries(
  release: Release,
  filters: WhatsNewFilters,
  can: PermissionCheck
): ReleaseEntry[] {
  return visibleEntries(release, can).filter((entry) => {
    if (filters.area && entry.area !== filters.area) return false;
    if (filters.showMeOnly && !entry.showMe) return false;
    return true;
  });
}

/** Areas that occur in what this user may see, in first-seen order. */
export function areasPresent(releases: Release[], can: PermissionCheck): EntryArea[] {
  const seen = new Set<EntryArea>();
  for (const release of releases) {
    for (const entry of visibleEntries(release, can)) seen.add(entry.area);
  }
  return [...seen];
}

export function countEntries(releases: Release[], can: PermissionCheck): number {
  return releases.reduce((sum, release) => sum + visibleEntries(release, can).length, 0);
}
