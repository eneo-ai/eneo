import { compareVersions, visibleEntries } from "@eneo/whats-new";
import type { EntryArea, Release, ReleaseEntry } from "@eneo/whats-new";

export type Marker = string | null | undefined;
export type ReleaseFilters = { area: EntryArea | null; showMeOnly: boolean };

export function pendingAnnouncement(
  enabled: boolean,
  latest: Release | undefined,
  announced: Marker
): Release | null {
  if (!enabled || !latest || announced === undefined) return null;
  if (announced && compareVersions(latest.version, announced) <= 0) return null;
  return latest;
}

export function shouldShowAnnouncement(release: Release, userCreatedAt: string | null | undefined) {
  if (!release.date || !userCreatedAt) return true;
  const [year = 0, month = 1, day = 1] = release.date.split("-").map(Number);
  return new Date(userCreatedAt) <= new Date(year, month - 1, day);
}

export function isReadRelease(release: Release, seenAtOpen: string | null): boolean {
  return Boolean(seenAtOpen && compareVersions(release.version, seenAtOpen) <= 0);
}

export function areasPresent(release: Release, isAdmin: boolean): EntryArea[] {
  return [...new Set(visibleEntries(release, isAdmin).map((entry) => entry.area))];
}

export function filterEntries(
  release: Release,
  filters: ReleaseFilters,
  isAdmin: boolean
): ReleaseEntry[] {
  return visibleEntries(release, isAdmin).filter(
    (entry) =>
      (!filters.area || entry.area === filters.area) && (!filters.showMeOnly || entry.showMe)
  );
}

export function tourEntries(release: Release, isAdmin: boolean): ReleaseEntry[] {
  return visibleEntries(release, isAdmin).filter((entry) => entry.showMe);
}
