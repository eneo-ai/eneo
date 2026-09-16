import { visibleEntries } from "@eneo/whats-new";
import type { Locale, Release } from "@eneo/whats-new";

export const ANNOUNCEMENT_HEADLINES = 3;

/**
 * The titles to name in the one-time announcement and how many entries it
 * leaves unnamed, restricted to what this user may see.
 */
export function announcementSummary(release: Release, isAdmin: boolean, locale: Locale) {
  const entries = visibleEntries(release, isAdmin);
  const headlines = entries
    .slice(0, ANNOUNCEMENT_HEADLINES)
    .map((entry) => entry.title[locale] ?? entry.title.en);
  return { headlines, more: Math.max(0, entries.length - headlines.length), total: entries.length };
}
