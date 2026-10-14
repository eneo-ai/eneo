import { onMount } from "svelte";
import { get } from "svelte/store";
import { getEneo } from "$lib/core/Eneo";
import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
import type { IntegrationSyncProgress } from "./syncProgress";
import { SyncProgressTracker } from "./SyncProgressTracker.svelte";

const SETTLE_REFRESH_DELAY_MS = 3_000;

/** Live sync progress for the current space while the calling component is mounted. */
export function useSyncProgress(): SyncProgressTracker {
  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const tracker = new SyncProgressTracker({
    load: () =>
      eneo.integrations.knowledge.getSyncProgress({ space: get(currentSpace) }) as Promise<{
        items: IntegrationSyncProgress[];
      }>,
    // The worker drops the progress just before it commits the sync's results;
    // a second refresh shortly after picks up what the first one can miss.
    onSettled: () => {
      void refreshCurrentSpace("knowledge");
      setTimeout(() => void refreshCurrentSpace("knowledge"), SETTLE_REFRESH_DELAY_MS);
    }
  });

  onMount(() => {
    tracker.start();
    // Starting a sync from a menu refreshes the space; look for its progress right away.
    let first = true;
    const unsubscribe = currentSpace.subscribe(() => {
      if (first) first = false;
      else tracker.refresh();
    });
    return () => {
      unsubscribe();
      tracker.stop();
    };
  });

  return tracker;
}
