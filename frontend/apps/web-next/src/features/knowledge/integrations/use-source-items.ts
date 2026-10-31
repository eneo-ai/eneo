"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { IntegrationKnowledge } from "../knowledge";

/** The items loaded for the source route. */
export type LoadedItems = { items: IntegrationKnowledge[] };

/**
 * The cached space owns the source. If it lacks the route's items, show them
 * only until a successful reread. Query update counts belong to this
 * cache; wall clocks cannot reliably order the two snapshots.
 * Once seen in the cache, a removed item never falls back to the route snapshot.
 */
export function useSourceItems(
  routeId: string,
  cached: IntegrationKnowledge[],
  loaded: LoadedItems
): IntegrationKnowledge[] {
  const queryClient = useQueryClient();
  // Capture completed reads when the route arrives.
  const [arrivalReads] = useState(
    () => queryClient.getQueryState(["spaces", routeId])?.dataUpdateCount ?? 0
  );
  // Followed even when a read returns the same space, which leaves its data as it was.
  const reads = useSyncExternalStore(
    useCallback((listener) => queryClient.getQueryCache().subscribe(listener), [queryClient]),
    () => (queryClient.getQueryState(["spaces", routeId])?.dataUpdateCount ?? 0) - arrivalReads
  );
  const present = cached.length > 0;
  const [missingOnArrival] = useState(!present);
  const [seen, setSeen] = useState(present);
  if (present && !seen) setSeen(true);

  useEffect(() => {
    // Start a read after arrival; an older in-flight response may predate the import.
    if (missingOnArrival) {
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
    }
  }, [missingOnArrival, queryClient, routeId]);

  if (present) return cached;
  return !seen && reads === 0 ? loaded.items : [];
}
