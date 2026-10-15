"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import type { IntegrationKnowledge } from "../knowledge";
import { syncedListKeys, syncProgressQueryOptions } from "./queries";
import { finishedSyncs, type ProgressById } from "./sync-progress";
import { syncRevision } from "./sync-status";

const NOTHING_RUNS: ProgressById = {};

// The backend drops a sync's progress just before it commits the results, so
// one refresh can still read the old state; the second one catches the commit.
const SETTLE_RECHECK_MS = 3_000;

/**
 * Refetches an item's lists once the space shows a sync of it that the lists
 * predate. Cached lists keep showing until the new ones arrive.
 */
function useRefreshSyncedLists(spaceId: string, items: readonly IntegrationKnowledge[]) {
  const queryClient = useQueryClient();
  const seen = useRef<ReadonlyMap<string, string> | null>(null);

  useEffect(() => {
    const revisions = new Map(items.map((item) => [item.id, syncRevision(item)]));
    const before = seen.current;
    seen.current = revisions;
    if (!before) return;
    for (const [id, revision] of revisions) {
      const known = before.get(id);
      if (known === undefined || known === revision) continue;
      for (const queryKey of syncedListKeys(spaceId, id)) {
        void queryClient.invalidateQueries({ queryKey });
      }
    }
  }, [items, queryClient, spaceId]);
}

/**
 * The running syncs of the current space. When one finishes, the space (its
 * items' counts and statuses) is refreshed, and again a moment later; the
 * finished items' lists follow once the space shows their new sync.
 */
export function useSyncProgress(): ProgressById {
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const { data } = useQuery(syncProgressQueryOptions(browserApi, space.id));
  const progress = data ?? NOTHING_RUNS;
  const previous = useRef(progress);
  const rechecks = useRef<number[]>([]);

  useEffect(() => {
    const pending = rechecks.current;
    return () => pending.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    const finished = finishedSyncs(previous.current, progress);
    previous.current = progress;
    if (finished.length === 0) return;
    const refresh = () => void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
    refresh();
    rechecks.current.push(window.setTimeout(refresh, SETTLE_RECHECK_MS));
  }, [progress, queryClient, routeId]);

  useRefreshSyncedLists(space.id, space.knowledge.integration_knowledge_list.items);

  return progress;
}
