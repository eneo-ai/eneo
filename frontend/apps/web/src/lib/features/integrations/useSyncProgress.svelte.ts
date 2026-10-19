import { onMount, untrack } from "svelte";
import { fromStore, get } from "svelte/store";
import { getEneo } from "$lib/core/Eneo";
import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
import { pendingSyncs, reportedSyncs, untrackSyncs } from "./pendingSyncs";
import type { IntegrationSyncProgress } from "./syncProgress";
import { SyncProgressTracker } from "./SyncProgressTracker.svelte";

type Options = {
  /** Poll only while this holds, e.g. while the tab showing the progress is open. */
  active?: () => boolean;
};

/**
 * Live sync progress for the current space while the calling component is mounted.
 * It polls only while the space has integration knowledge, `active` holds and the
 * browser tab is visible; coming back to the tab polls at once. A sync queued from
 * a menu is polled for at once and fast, and shows as queued until it reports.
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
    const unsubscribePending = pendingSyncs.subscribe((pending) => {
      const ids = pending.map((item) => item.knowledgeId);
      const added = ids.some((id) => !tracker.pending.includes(id));
      tracker.pending = ids;
      if (added) tracker.refresh();
    });
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      unsubscribe();
      unsubscribePending();
      tracker.stop();
    };
  });

  // Once the worker reports on a queued sync, its progress tells the rest.
  $effect(() => {
    const byId = tracker.byId;
    if (tracker.pending.length === 0) return;
    const reported = reportedSyncs(get(pendingSyncs), byId);
    untrack(() => untrackSyncs(reported.map((item) => item.jobId)));
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
