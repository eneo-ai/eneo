"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { IntegrationKnowledge } from "../knowledge";

/** The items a source's server page found. */
export type LoadedItems = { items: IntegrationKnowledge[] };

/**
 * The cached space owns the source. If it lacks the server's items, show them
 * only until a successful client reread. Query update counts belong to this
 * browser; server and browser wall clocks cannot order the two snapshots.
 * Once seen in the cache, a removed item never falls back to the server copy.
 */
export function useSourceItems(
  routeId: string,
  cached: IntegrationKnowledge[],
  loaded: LoadedItems
): IntegrationKnowledge[] {
  const queryClient = useQueryClient();
  // Capture the browser's baseline even during hydration, when the external
  // store first exposes its server snapshot (zero updates since arrival).
  const [arrivalReads] = useState(
    () => queryClient.getQueryState(["spaces", routeId])?.dataUpdateCount ?? 0
  );
  // Followed even when a read returns the same space, which leaves its data as it was.
  const reads = useSyncExternalStore(
    useCallback((listener) => queryClient.getQueryCache().subscribe(listener), [queryClient]),
    () => (queryClient.getQueryState(["spaces", routeId])?.dataUpdateCount ?? 0) - arrivalReads,
    () => 0
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
