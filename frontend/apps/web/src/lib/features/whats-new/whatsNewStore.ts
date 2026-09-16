import { createContext } from "$lib/core/context";
import type { Eneo } from "@eneo/eneo-js";
import { compareVersions, hasUnseenRelease, latestRelease } from "@eneo/whats-new";
import { derived, get, writable } from "svelte/store";

export { getWhatsNewStore, initWhatsNewStore, createWhatsNewStore };

/** `null` = never; `undefined` = unknown (state could not be read). */
export type Marker = string | null | undefined;

export interface WhatsNewInit {
  eneo: { whatsNew: Pick<Eneo["whatsNew"], "markSeen" | "markAnnounced" | "resetState"> };
  /** Tenant opt-out (admin setting): off hides the page, dot and announcement. */
  whatsNewEnabled: boolean;
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
  const enabled = writable(data.whatsNewEnabled);
  const seenVersion = writable<Marker>(data.whatsNewSeenVersion);
  const announcedVersion = writable<Marker>(data.whatsNewAnnouncedVersion);
  const hasUnseen = derived([enabled, seenVersion], ([$enabled, $seen]) =>
    !$enabled || $seen === undefined ? false : hasUnseenRelease($seen)
  );

  let inFlight: Promise<void> | null = null;

  /** Record the newest bundled release as seen. Safe to call repeatedly. */
  function markLatestSeen(): Promise<void> {
    if (!get(enabled)) return Promise.resolve();
    if (inFlight) return inFlight;
    const latest = latestRelease();
    const seen = get(seenVersion);
    if (!latest || seen === undefined || !hasUnseenRelease(seen)) return Promise.resolve();

    // Optimistic: the dot disappears immediately and returns if saving fails.
    const previous = get(seenVersion);
    seenVersion.set(latest.version);
    inFlight = eneo.whatsNew
      .markSeen(latest.version)
      .then((state) => seenVersion.set(state.seen_version))
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
   * The release to announce once, or null when the user has already been
   * shown an announcement for the newest bundled release (or newer).
   */
  function pendingAnnouncement() {
    const latest = latestRelease();
    if (!get(enabled) || !latest) return null;
    const announced = get(announcedVersion);
    if (announced === undefined) return null;
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
    announcedVersion.set(latest.version);
    return eneo.whatsNew
      .markAnnounced(latest.version)
      .then((state) => announcedVersion.set(state.announced_version))
      .catch((error: unknown) => {
        console.error("Could not record the What's new announcement", error);
      });
  }

  /** Development only: forget both markers so the announcement and the dot return. */
  async function resetState(): Promise<void> {
    await eneo.whatsNew.resetState();
    seenVersion.set(null);
    announcedVersion.set(null);
  }

  return {
    enabled: { subscribe: enabled.subscribe },
    setEnabled: enabled.set,
    resetState,
    seenVersion: { subscribe: seenVersion.subscribe },
    announcedVersion: { subscribe: announcedVersion.subscribe },
    hasUnseen,
    markLatestSeen,
    pendingAnnouncement,
    markLatestAnnounced
  };
}
