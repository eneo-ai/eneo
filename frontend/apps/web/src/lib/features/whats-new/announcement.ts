import { visibleEntries } from "@eneo/whats-new";
import type { PermissionCheck, Release, ReleaseEntry } from "@eneo/whats-new";

export const ANNOUNCEMENT_ENTRIES = 4;

/**
 * What the one-time announcement shows: the first few entries this user may
 * see and how many the page holds beyond them.
 */
export function announcementSummary(
  release: Release,
  can: PermissionCheck
): { entries: ReleaseEntry[]; more: number; total: number } {
  const all = visibleEntries(release, can);
  const entries = all.slice(0, ANNOUNCEMENT_ENTRIES);
  return { entries, more: all.length - entries.length, total: all.length };
}
