"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { reportedSyncs, untrackSyncs, usePendingSyncs } from "./pending-syncs";
import { syncProgressQueryOptions } from "./queries";
import type { QueuedIds } from "./sources";
import { finishedSyncs, type ProgressById } from "./sync-progress";

const NOTHING_RUNS: ProgressById = {};

/**
 * The running syncs of the current space, and its items whose sync was queued
 * from here (pending-syncs.ts) and that no worker has reported on yet. It
 * polls only while the space has integration knowledge of its own, fast while
 * a queued sync waits. When a sync finishes, the space (its items' counts,
 * statuses and sync revisions) is refreshed, and the lists keyed by an item's
 * revision follow. `loaded` is false until the first poll has answered: until
 * then `progress` says nothing runs only for want of knowing.
 */
export function useSyncProgress(): {
  progress: ProgressById;
  queued: QueuedIds;
  loaded: boolean;
} {
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const ownItems = space.knowledge.integration_knowledge_list.items.filter(
    (item) => item.space_id === space.id
  );
  const hasOwnKnowledge = ownItems.length > 0;
  const allPending = usePendingSyncs();
  const ownIds = ownItems.map((item) => item.id).join(" ");
  const pending = useMemo(() => {
    const ids = new Set(ownIds.split(" "));
    return allPending.filter((entry) => ids.has(entry.knowledgeId));
  }, [allPending, ownIds]);
  const { data, isPending } = useQuery({
    ...syncProgressQueryOptions(
      browserApi,
      space.id,
      pending.map((entry) => entry.knowledgeId)
    ),
    enabled: hasOwnKnowledge
  });
  const progress = (hasOwnKnowledge ? data : undefined) ?? NOTHING_RUNS;
  const previous = useRef(progress);

  useEffect(() => {
    const finished = finishedSyncs(previous.current, progress);
    previous.current = progress;
    // The backend keeps a sync's progress until the sync's transaction has
    // ended (a 120 s expiry clears it otherwise), so once it is gone the space
    // holds the results. Invalidating cancels a refetch that started before.
    if (finished.length > 0) void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
  }, [progress, queryClient, routeId]);

  // Once the worker reports on a queued sync, its progress tells the rest.
  useEffect(() => {
    const reported = reportedSyncs(pending, progress);
    if (reported.length > 0) untrackSyncs(reported.map((entry) => entry.jobId));
  }, [pending, progress]);

  const queued = useMemo<QueuedIds>(() => {
    const reported = new Set(reportedSyncs(pending, progress).map((entry) => entry.knowledgeId));
    return new Set(
      pending.filter((entry) => !reported.has(entry.knowledgeId)).map((entry) => entry.knowledgeId)
    );
  }, [pending, progress]);

  return { progress, queued, loaded: !hasOwnKnowledge || !isPending };
}
