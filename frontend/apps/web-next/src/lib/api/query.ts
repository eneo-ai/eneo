import { defaultShouldDehydrateQuery, isServer, QueryClient } from "@tanstack/react-query";

/**
 * TanStack Query setup for the App Router hydration pattern: server
 * components prefetch into a per-request QueryClient and pass
 * `dehydrate(queryClient)` through a <HydrationBoundary>; client components
 * pick the data up with useQuery without refetching on mount.
 *
 * Query key convention: keys mirror backend resource paths —
 * ["dashboard"], ["spaces", spaceId], ["spaces", spaceId, "applications"].
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Server-rendered data is fresh long enough that hydration does not
        // immediately refetch it on the client.
        staleTime: 30_000
      },
      dehydrate: {
        // Also dehydrate in-flight prefetches so suspended server components
        // can stream them to the client.
        shouldDehydrateQuery: (query) =>
          defaultShouldDehydrateQuery(query) || query.state.status === "pending"
      }
    }
  });
}

let browserQueryClient: QueryClient | undefined;

/**
 * On the server: a fresh client per call (no cross-request state). In the
 * browser: a singleton that survives suspense-driven re-renders.
 */
export function getQueryClient(): QueryClient {
  if (isServer) return makeQueryClient();
  return (browserQueryClient ??= makeQueryClient());
}
