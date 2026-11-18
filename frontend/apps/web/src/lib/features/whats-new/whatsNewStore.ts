import { createContext } from "$lib/core/context";
import { hasPermission } from "$lib/core/hasPermission";
import type { Eneo, Role } from "@eneo/eneo-js";
import {
  compareVersions,
  hasUnseenRelease,
  latestRelease,
  releasesForVersion,
  visibleEntries
} from "@eneo/whats-new";
import { derived, get, writable } from "svelte/store";

export { getWhatsNewStore, initWhatsNewStore, createWhatsNewStore };

/** `null` = never; `undefined` = unknown (state could not be read). */
export type Marker = string | null | undefined;

export interface WhatsNewInit {
  user: { id: string; roles?: Role[]; predefined_roles?: Role[] };
  eneo: { whatsNew: Pick<Eneo["whatsNew"], "markSeen" | "markAnnounced" | "resetState"> };
  /** Tenant opt-out (admin setting): off hides the page, dot and announcement. */
  whatsNewEnabled: boolean;
  /** Installed frontend version, including the RC suffix. */
  whatsNewVersion: string;
  whatsNewSeenVersion: Marker;
  whatsNewAnnouncedVersion: Marker;
}

const [getWhatsNewStore, setWhatsNewStore] =
  createContext<ReturnType<typeof createWhatsNewStore>>("What's new");

function initWhatsNewStore(data: WhatsNewInit) {
  const store = createWhatsNewStore(data);
  setWhatsNewStore(store);
  return store;
}

function createWhatsNewStore(data: WhatsNewInit) {
  const { eneo } = data;
  const bundled = releasesForVersion(data.whatsNewVersion);
  const can = hasPermission(data.user);
  const releases = bundled.filter((release) => visibleEntries(release, can).length > 0);
  // Unreleased notes on development builds are listed, never announced or recorded.
  const latest = latestRelease(bundled);
  const latestVisible = latest && visibleEntries(latest, can).length > 0;
  // Local reminders are isolated by account and installed release (including RCs).
  const reminderKey = `eneo:whats-new:remind-after:${data.user.id}:${latest?.version}`;
  const enabled = writable(data.whatsNewEnabled);
  const seenVersion = writable<Marker>(data.whatsNewSeenVersion);
  const announcedVersion = writable<Marker>(data.whatsNewAnnouncedVersion);
  const hasUnseen = derived([enabled, seenVersion], ([$enabled, $seen]) =>
    !$enabled || $seen === undefined
      ? false
      : releases.some((release) => hasUnseenRelease($seen, release))
  );

  let inFlight: Promise<void> | null = null;

  function reminderTime(): number | null {
    try {
      const raw = globalThis.localStorage?.getItem(reminderKey);
      if (!raw) return null;
      const timestamp = Number(raw);
      return Number.isFinite(timestamp) && timestamp > 0 ? timestamp : null;
    } catch {
      // Storage may be unavailable; ordinary announcements must still work.
      return null;
    }
  }

  function forgetReminder(): void {
    try {
      globalThis.localStorage?.removeItem(reminderKey);
    } catch {
      // Storage failures must not prevent reading or announcing news.
    }
  }

  /** Record the newest bundled release as seen. Safe to call repeatedly. */
  function markLatestSeen(): Promise<void> {
    if (!get(enabled)) return Promise.resolve();
    if (inFlight) return inFlight;
    if (!get(hasUnseen)) return Promise.resolve();
    const seen = get(seenVersion);
    if (!latest || seen === undefined || !hasUnseenRelease(seen, latest)) return Promise.resolve();

    // Optimistic: the dot disappears immediately and returns if saving fails.
    const previous = get(seenVersion);
    seenVersion.set(latest.version);
    inFlight = eneo.whatsNew
      .markSeen(latest.version)
      .then((state) => {
        seenVersion.set(state.seen_version);
        if (!hasUnseenRelease(state.seen_version, latest)) forgetReminder();
      })
      .catch((error: unknown) => {
        seenVersion.set(previous);
        console.error("Could not record What's new as seen", error);
      })
      .finally(() => {
        inFlight = null;
      });
    return inFlight;
  }

  /**
   * Announce new releases or due local reminders. A reminder never delays
   * a different release, and server-side read progress cancels it.
   */
  function pendingAnnouncement() {
    if (!get(enabled) || !latest || !latestVisible) return null;
    const announced = get(announcedVersion);
    if (announced === undefined) return null;
    if (announced && compareVersions(latest.version, announced) < 0) return null;
    const remindAfter = reminderTime();
    if (remindAfter !== null) {
      if (!get(hasUnseen)) {
        forgetReminder();
        return null;
      }
      return Date.now() >= remindAfter ? latest : null;
    }
    if (announced && compareVersions(latest.version, announced) <= 0) return null;
    return latest;
  }

  /**
   * Record the announcement as shown. Written when it is shown, not when it
   * is dismissed, so a reload without dismissing does not repeat it; the
   * seen marker is untouched because being told is not the same as looking.
   */
  function markLatestAnnounced(): Promise<void> {
    const latest = pendingAnnouncement();
    if (!latest) return Promise.resolve();
    forgetReminder();
    announcedVersion.set(latest.version);
    return eneo.whatsNew
      .markAnnounced(latest.version)
      .then((state) => announcedVersion.set(state.announced_version))
      .catch((error: unknown) => {
        console.error("Could not record the What's new announcement", error);
      });
  }

  function snoozeLatest(): void {
    if (!get(enabled) || !latest || !latestVisible || !get(hasUnseen)) return;
    // Let blocked/full storage throw: the dialog stays open and explains failure.
    globalThis.localStorage.setItem(reminderKey, String(Date.now() + 24 * 60 * 60 * 1000));
  }

  /** Development only: forget server markers and this browser's reminder. */
  async function resetState(): Promise<void> {
    // Unlike best-effort cleanup, reset must not claim success if removal fails.
    globalThis.localStorage?.removeItem(reminderKey);
    await eneo.whatsNew.resetState();
    seenVersion.set(null);
    announcedVersion.set(null);
  }

  return {
    releases,
    enabled: { subscribe: enabled.subscribe },
    setEnabled: enabled.set,
    resetState,
    seenVersion: { subscribe: seenVersion.subscribe },
    announcedVersion: { subscribe: announcedVersion.subscribe },
    hasUnseen,
    markLatestSeen,
    pendingAnnouncement,
    markLatestAnnounced,
    snoozeLatest
  };
}
