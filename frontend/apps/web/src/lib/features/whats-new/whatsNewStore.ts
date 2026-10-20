import { createContext } from "$lib/core/context";
import type { Eneo } from "@eneo/eneo-js";
import { compareVersions, hasUnseenRelease, releasesForVersion } from "@eneo/whats-new";
import { derived, get, writable } from "svelte/store";

export { getWhatsNewStore, initWhatsNewStore, createWhatsNewStore };

/** `null` = never; `undefined` = unknown (state could not be read). */
export type Marker = string | null | undefined;

export interface WhatsNewInit {
  eneo: {
    whatsNew: Pick<Eneo["whatsNew"], "markSeen" | "markAnnounced" | "snooze" | "resetState">;
  };
  /** Tenant opt-out (admin setting): off hides the page, dot and announcement. */
  whatsNewEnabled: boolean;
  /** Installed frontend version, including the RC suffix. */
  whatsNewVersion: string;
  whatsNewSeenVersion: Marker;
  whatsNewAnnouncedVersion: Marker;
  whatsNewRemindAfter: string | null | undefined;
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
  const releases = releasesForVersion(data.whatsNewVersion);
  const latest = releases[0];
  const enabled = writable(data.whatsNewEnabled);
  const seenVersion = writable<Marker>(data.whatsNewSeenVersion);
  const announcedVersion = writable<Marker>(data.whatsNewAnnouncedVersion);
  let remindAfter = data.whatsNewRemindAfter;
  const hasUnseen = derived([enabled, seenVersion], ([$enabled, $seen]) =>
    !$enabled || $seen === undefined ? false : hasUnseenRelease($seen, latest)
  );

  let inFlight: Promise<void> | null = null;
  let announcementWrite: Promise<void> | null = null;

  /** Record the newest bundled release as seen. Safe to call repeatedly. */
  function markLatestSeen(): Promise<void> {
    if (!get(enabled)) return Promise.resolve();
    if (inFlight) return inFlight;
    const seen = get(seenVersion);
    if (!latest || seen === undefined || !hasUnseenRelease(seen, latest)) return Promise.resolve();

    // Optimistic: the dot disappears immediately and returns if saving fails.
    const previous = get(seenVersion);
    seenVersion.set(latest.version);
    inFlight = eneo.whatsNew
      .markSeen(latest.version)
      .then((state) => {
        seenVersion.set(state.seen_version);
        remindAfter = state.remind_after;
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
   * Announce a new release, or repeat its unread announcement when the saved
   * reminder is due. A reminder never delays a newer release.
   */
  function pendingAnnouncement() {
    if (!get(enabled) || !latest) return null;
    const announced = get(announcedVersion);
    if (announced === undefined) return null;
    if (announced) {
      const order = compareVersions(latest.version, announced);
      if (order < 0) return null;
      if (
        order === 0 &&
        (!get(hasUnseen) ||
          !remindAfter ||
          Date.parse(remindAfter) > Date.now() ||
          !Number.isFinite(Date.parse(remindAfter)))
      )
        return null;
    }
    return latest;
  }

  /**
   * Record the announcement as shown. Written when it is shown, not when it
   * is dismissed, so a reload without dismissing does not repeat it; the
   * seen marker is untouched because being told is not the same as looking.
   */
  function markLatestAnnounced(): Promise<void> {
    if (announcementWrite) return announcementWrite;
    const latest = pendingAnnouncement();
    if (!latest) return Promise.resolve();
    announcedVersion.set(latest.version);
    remindAfter = null;
    announcementWrite = eneo.whatsNew
      .markAnnounced(latest.version)
      .then((state) => {
        announcedVersion.set(state.announced_version);
        remindAfter = state.remind_after;
      })
      .catch((error: unknown) => {
        console.error("Could not record the What's new announcement", error);
      })
      .finally(() => {
        announcementWrite = null;
      });
    return announcementWrite;
  }

  async function snoozeLatest(): Promise<void> {
    if (!get(enabled) || !latest) return;
    // Opening and immediately postponing must not race the announcement write.
    await announcementWrite;
    const state = await eneo.whatsNew.snooze(latest.version);
    seenVersion.set(state.seen_version);
    announcedVersion.set(state.announced_version);
    remindAfter = state.remind_after;
  }

  /** Development only: forget both markers so the announcement and the dot return. */
  async function resetState(): Promise<void> {
    await eneo.whatsNew.resetState();
    seenVersion.set(null);
    announcedVersion.set(null);
    remindAfter = null;
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
