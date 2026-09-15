import { createContext } from "$lib/core/context";
import type { Eneo } from "@eneo/eneo-js";
import { hasUnseenRelease, latestRelease } from "@eneo/whats-new";
import { derived, get, writable } from "svelte/store";

export { getWhatsNewStore, initWhatsNewStore, createWhatsNewStore };

const [getWhatsNewStore, setWhatsNewStore] =
  createContext<ReturnType<typeof createWhatsNewStore>>("What's new");

function initWhatsNewStore(data: { eneo: Eneo; whatsNewSeenVersion: string | null }) {
  setWhatsNewStore(createWhatsNewStore(data));
}

function createWhatsNewStore(data: { eneo: Eneo; whatsNewSeenVersion: string | null }) {
  const { eneo } = data;
  const seenVersion = writable<string | null>(data.whatsNewSeenVersion);
  const hasUnseen = derived(seenVersion, ($seen) => hasUnseenRelease($seen));

  let inFlight: Promise<void> | null = null;

  /** Record the newest bundled release as seen. Safe to call repeatedly. */
  function markLatestSeen(): Promise<void> {
    const latest = latestRelease();
    if (!latest || !hasUnseenRelease(currentSeen())) return Promise.resolve();
    if (inFlight) return inFlight;

    // Optimistic: the dot disappears immediately; a failed write only means
    // the dot returns on the next full load.
    const previous = currentSeen();
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

  function currentSeen(): string | null {
    return get(seenVersion);
  }

  return {
    seenVersion: { subscribe: seenVersion.subscribe },
    hasUnseen,
    markLatestSeen
  };
}
