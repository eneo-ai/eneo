import { createContext } from "$lib/core/context";
import type { Eneo } from "@eneo/eneo-js";
import { compareVersions, hasUnseenRelease, latestRelease } from "@eneo/whats-new";
import { derived, get, writable } from "svelte/store";

export { getWhatsNewStore, initWhatsNewStore, createWhatsNewStore };

export interface WhatsNewInit {
  eneo: Eneo;
  whatsNewSeenVersion: string | null;
  whatsNewAnnouncedVersion: string | null;
}

const [getWhatsNewStore, setWhatsNewStore] =
  createContext<ReturnType<typeof createWhatsNewStore>>("What's new");

function initWhatsNewStore(data: WhatsNewInit) {
  setWhatsNewStore(createWhatsNewStore(data));
}

function createWhatsNewStore(data: WhatsNewInit) {
  const { eneo } = data;
  const seenVersion = writable<string | null>(data.whatsNewSeenVersion);
  const announcedVersion = writable<string | null>(data.whatsNewAnnouncedVersion);
  const hasUnseen = derived(seenVersion, ($seen) => hasUnseenRelease($seen));

  let inFlight: Promise<void> | null = null;

  /** Record the newest bundled release as seen. Safe to call repeatedly. */
  function markLatestSeen(): Promise<void> {
    const latest = latestRelease();
    if (!latest || !hasUnseenRelease(get(seenVersion))) return Promise.resolve();
    if (inFlight) return inFlight;

    // Optimistic: the dot disappears immediately; a failed write only means
    // the dot returns on the next full load.
    const previous = get(seenVersion);
    seenVersion.set(latest.version);
    inFlight = eneo.whatsNew
      .markSeen(latest.version)
      .then(() => undefined)
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
    if (!latest) return null;
    const announced = get(announcedVersion);
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
      .then(() => undefined)
      .catch((error: unknown) => {
        console.error("Could not record the What's new announcement", error);
      });
  }

  return {
    seenVersion: { subscribe: seenVersion.subscribe },
    announcedVersion: { subscribe: announcedVersion.subscribe },
    hasUnseen,
    markLatestSeen,
    pendingAnnouncement,
    markLatestAnnounced
  };
}
