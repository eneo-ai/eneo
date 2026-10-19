"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { IntegrationKnowledge } from "../knowledge";

/** The items a source's server page found, and when it read the space (its `dataUpdatedAt`). */
export type LoadedItems = { items: IntegrationKnowledge[]; readAt: number };

/**
 * The items a source's page shows: `cached`, the source's items in the cached
 * space. That cache can predate the page's server render, such as an item
 * imported since: the items the server found then stand in, and the space is
 * read again. A cache read after the server's (Back to a source deleted since,
 * from the router's cache), or one that has shown the items, is the truth:
 * they are gone once it lacks them.
 */
export function useSourceItems(
  routeId: string,
  cached: IntegrationKnowledge[],
  loaded: LoadedItems
): IntegrationKnowledge[] {
  const queryClient = useQueryClient();
  // Followed even when a read returns the same space, which leaves its data as it was.
  const cacheReadAt = useSyncExternalStore(
    useCallback((listener) => queryClient.getQueryCache().subscribe(listener), [queryClient]),
    () => queryClient.getQueryState(["spaces", routeId])?.dataUpdatedAt ?? 0,
    () => 0
  );
  const present = cached.length > 0;
  const [missingOnArrival] = useState(!present);
  const [seen, setSeen] = useState(present);
  if (present && !seen) setSeen(true);

  useEffect(() => {
    // Joins a read already under way (useSpace refetches a stale space on mount).
    if (missingOnArrival) {
      void queryClient.invalidateQueries(
        { queryKey: ["spaces", routeId] },
        { cancelRefetch: false }
      );
    }
  }, [missingOnArrival, queryClient, routeId]);

  if (present) return cached;
  return !seen && cacheReadAt < loaded.readAt ? loaded.items : [];
}
