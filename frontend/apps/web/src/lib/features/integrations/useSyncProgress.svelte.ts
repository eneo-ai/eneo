import { onMount, untrack } from "svelte";
import { fromStore, get } from "svelte/store";
import { getEneo } from "$lib/core/Eneo";
import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
import type { IntegrationSyncProgress } from "./syncProgress";
import { SyncProgressTracker } from "./SyncProgressTracker.svelte";

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

  const tracker = new SyncProgressTracker({
    load: () =>
      eneo.integrations.knowledge.getSyncProgress({ space: get(currentSpace) }) as Promise<{
        items: IntegrationSyncProgress[];
      }>,
    // The worker clears a sync's progress only after its transaction commits, so
    // the space read now already holds what the sync wrote.
    onSettled: () => void refreshCurrentSpace("knowledge")
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
