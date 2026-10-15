import { onMount, untrack } from "svelte";
import { fromStore, get } from "svelte/store";
import { getEneo } from "$lib/core/Eneo";
import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
import type { IntegrationSyncProgress } from "./syncProgress";
import { SyncProgressTracker } from "./SyncProgressTracker.svelte";

const SETTLE_REFRESH_DELAY_MS = 3_000;

type Options = {
  /** Poll only while this holds, e.g. while the tab showing the progress is open. */
  active?: () => boolean;
};

/**
 * Live sync progress for the current space while the calling component is mounted.
 * It polls only while the space has integration knowledge, `active` holds and the
 * browser tab is visible; coming back to the tab polls at once.
 */
export function useSyncProgress({ active = () => true }: Options = {}): SyncProgressTracker {
  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();
  const space = fromStore(currentSpace);
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- timer handles, never rendered
  const settleTimers = new Set<ReturnType<typeof setTimeout>>();

  const tracker = new SyncProgressTracker({
    load: () =>
      eneo.integrations.knowledge.getSyncProgress({ space: get(currentSpace) }) as Promise<{
        items: IntegrationSyncProgress[];
      }>,
    // The worker drops the progress just before it commits the sync's results;
    // a second refresh shortly after picks up what the first one can miss.
    onSettled: () => {
      void refreshCurrentSpace("knowledge");
      const timer = setTimeout(() => {
        settleTimers.delete(timer);
        void refreshCurrentSpace("knowledge");
      }, SETTLE_REFRESH_DELAY_MS);
      settleTimers.add(timer);
    }
  });

  let visible = $state(true);

  onMount(() => {
    visible = !document.hidden;
    const onVisibilityChange = () => (visible = !document.hidden);
    document.addEventListener("visibilitychange", onVisibilityChange);
    // Starting a sync from a menu refreshes the space; look for its progress right away.
    let first = true;
    const unsubscribe = currentSpace.subscribe(() => {
      if (first) first = false;
      else tracker.refresh();
    });
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      unsubscribe();
      tracker.stop();
      for (const timer of settleTimers) clearTimeout(timer);
      settleTimers.clear();
    };
  });

  const hasKnowledge = $derived(
    space.current.knowledge.integrationKnowledge.some((item) => item.space_id === space.current.id)
  );

  $effect(() => {
    const poll = visible && active() && hasKnowledge;
    untrack(() => (poll ? tracker.start() : tracker.stop()));
  });

  return tracker;
}
