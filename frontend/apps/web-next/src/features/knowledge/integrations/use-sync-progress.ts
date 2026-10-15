"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { syncProgressQueryOptions } from "./queries";
import { finishedSyncs, type ProgressById } from "./sync-progress";

const NOTHING_RUNS: ProgressById = {};

// The backend drops a sync's progress just before it commits the results, so
// one refresh can still read the old state; the second one catches the commit.
const SETTLE_RECHECK_MS = 3_000;

/**
 * The running syncs of the current space. When one finishes, the space (its
 * items' counts and statuses) and the finished items' lists are refreshed.
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
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      // Document, skipped-file and sync-log queries carry the item id in their key.
      void queryClient.invalidateQueries({
        predicate: ({ queryKey }) =>
          queryKey[0] === "integrations" &&
          finished.some((id) => JSON.stringify(queryKey).includes(id))
      });
    };
    refresh();
    rechecks.current.push(window.setTimeout(refresh, SETTLE_RECHECK_MS));
  }, [progress, queryClient, routeId]);

  return progress;
}
