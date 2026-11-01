import type { Permission } from "@eneo/eneo-js";

export type Locale = "en" | "sv";
export type Localized = Record<Locale, string>;

export type EntryType = "new" | "improved" | "fixed";
export type EntryArea =
  "chat" | "assistants" | "knowledge" | "spaces" | "skills" | "account" | "admin" | "platform";
export type EntryAudience = "all" | "admin";

/** Uses the same allOf AND anyOf contract as the app permission checker. */
export type EntryPermissions = { allOf?: Permission[]; anyOf?: Permission[] };
export type PermissionCheck = (required: Permission | EntryPermissions) => boolean;

export interface ShowMe {
  /** App-relative path without locale prefix. */
  href: string;
  /** Value of a `data-tour` attribute in the web app. */
  anchor: string;
}

export interface ReleaseEntry {
  id: string;
  /** Published ids of entries merged into this one; preserved as deep-link anchors. */
  aliases?: string[];
  type: EntryType;
  area: EntryArea;
  audience?: EntryAudience;
  /** Omit for general news. Admin audience is an additional requirement. */
  permissions?: EntryPermissions;
  title: Localized;
  body: Localized;
  showMe?: ShowMe;
}

export interface Release {
  /** Semver without a leading v, e.g. "2.2.0", or `UNRELEASED` on develop. */
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

/** Version of the develop-only block for merged changes no final release includes yet. */
export const UNRELEASED: "next";

/** Whether the release is the unreleased block, which is never announced or recorded. */
export function isUnreleased(release: Release): boolean;

/** Semver order for release ids; negative when a < b. Pre-releases sort before their final; `UNRELEASED` last. */
export function compareVersions(a: string, b: string): number;

/** The newest released (not `UNRELEASED`) entry in `list`, by default releases.json. */
export function latestRelease(list?: Release[]): Release | undefined;

/** Bind matching release notes to the installed RC version; docs keep the authored versions. */
export function releasesForVersion(installedVersion: string): Release[];

/**
 * Whether the newest bundled release is newer than the one the user has seen.
 * `seenVersion` is the value stored by the backend (null before the first visit).
 * Always false for the `UNRELEASED` block.
 */
export function hasUnseenRelease(seenVersion: string | null | undefined, latest?: Release): boolean;

/** Entries allowed by the user’s actual permission checker; admin is not a bypass. */
export function visibleEntries(release: Release, can: PermissionCheck): ReleaseEntry[];
