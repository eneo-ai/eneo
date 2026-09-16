import { compareVersions, visibleEntries } from "@eneo/whats-new";
import type { EntryArea, Release, ReleaseEntry } from "@eneo/whats-new";

export interface WhatsNewFilters {
  /** `null` = every area. */
  area: EntryArea | null;
  /** Only entries with a Show me target. */
  showMeOnly: boolean;
  /** Include releases the user had already seen when they opened the page. */
  showRead: boolean;
}

export interface FilteredRelease extends Release {
  read: boolean;
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

export function hasUnreadRelease(releases: Release[], seenAtOpen: string | null): boolean {
  return releases.some((release) => !isReadRelease(release, seenAtOpen));
}

/** Filters an audience may see, with `read` stamped per release; empty releases drop out. */
export function applyFilters(
  releases: Release[],
  filters: WhatsNewFilters,
  seenAtOpen: string | null,
  isAdmin: boolean
): FilteredRelease[] {
  return releases
    .map((release) => ({ ...release, read: isReadRelease(release, seenAtOpen) }))
    .filter((release) => filters.showRead || !release.read)
    .map((release) => ({
      ...release,
      entries: visibleEntries(release, isAdmin).filter((entry) => matches(entry, filters))
    }))
    .filter((release) => release.entries.length > 0);
}

function matches(entry: ReleaseEntry, filters: WhatsNewFilters): boolean {
  if (filters.area && entry.area !== filters.area) return false;
  if (filters.showMeOnly && !entry.showMe) return false;
  return true;
}

/** Areas that occur in what this audience may see, in first-seen order. */
export function areasPresent(releases: Release[], isAdmin: boolean): EntryArea[] {
  const seen = new Set<EntryArea>();
  for (const release of releases) {
    for (const entry of visibleEntries(release, isAdmin)) seen.add(entry.area);
  }
  return [...seen];
}

export function countEntries(releases: Release[], isAdmin: boolean): number {
  return releases.reduce((sum, release) => sum + visibleEntries(release, isAdmin).length, 0);
}
