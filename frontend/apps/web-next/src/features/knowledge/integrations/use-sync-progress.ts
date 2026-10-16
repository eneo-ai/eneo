"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { syncProgressQueryOptions } from "./queries";
import { finishedSyncs, type ProgressById } from "./sync-progress";

const NOTHING_RUNS: ProgressById = {};

/**
 * The running syncs of the current space; it polls only while the space has
 * integration knowledge of its own. When one finishes, the space (its items'
 * counts, statuses and sync revisions) is refreshed, and the lists keyed by an
 * item's revision follow.
 */
export function useSyncProgress(): ProgressById {
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const hasOwnKnowledge = space.knowledge.integration_knowledge_list.items.some(
    (item) => item.space_id === space.id
  );
  const { data } = useQuery({
    ...syncProgressQueryOptions(browserApi, space.id),
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

  return progress;
}
