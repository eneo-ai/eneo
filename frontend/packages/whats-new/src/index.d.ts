export type Locale = "en" | "sv";
export type Localized = Record<Locale, string>;

export type EntryType = "new" | "improved" | "fixed";
export type EntryArea =
  "chat" | "assistants" | "knowledge" | "spaces" | "skills" | "account" | "admin" | "platform";
export type EntryAudience = "all" | "admin";

export interface ShowMe {
  /** App-relative path without locale prefix. */
  href: string;
  /** Value of a `data-tour` attribute in the web app. */
  anchor: string;
}

export interface ReleaseEntry {
  id: string;
  type: EntryType;
  area: EntryArea;
  audience?: EntryAudience;
  title: Localized;
  body: Localized;
  showMe?: ShowMe;
}

export interface Release {
  /** Semver without a leading v, e.g. "2.2.0". */
  version: string;
  /** YYYY-MM-DD; absent while the release is a draft. */
  date?: string;
  entries: ReleaseEntry[];
}

/** All releases, newest first, exactly as in releases.json. */
export const releases: Release[];

/** Closed vocabularies, read from releases.schema.json at runtime. */
export const ENTRY_TYPES: readonly EntryType[];
export const ENTRY_AREAS: readonly EntryArea[];
export const ENTRY_AUDIENCES: readonly EntryAudience[];
export const LOCALES: readonly Locale[];

/** Semver order for release ids; negative when a < b. Pre-releases sort before their final. */
export function compareVersions(a: string, b: string): number;

/** The newest release, or undefined when releases.json is empty. */
export function latestRelease(): Release | undefined;

/**
 * Whether the newest bundled release is newer than the one the user has seen.
 * `seenVersion` is the value stored by the backend (null before the first visit).
 */
export function hasUnseenRelease(seenVersion: string | null | undefined): boolean;

/** Entries the given user may see (admin-only entries need `isAdmin`). */
export function visibleEntries(release: Release, isAdmin: boolean): ReleaseEntry[];
