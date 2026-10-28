import {
  defaultShouldDehydrateQuery,
  environmentManager,
  QueryClient,
  type DefaultError,
  type QueryExecuteOptions,
  type QueryKey
} from "@tanstack/react-query";
import { EneoApiError, isFinalError } from "./errors";

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
        staleTime: 30_000,
        retry: retryTransientFailure
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

/**
 * The default retry policy (a query with its own `retry` keeps it): a refusal
 * (4xx) is final, asking again won't change it; a server or network failure
 * is tried three more times. The server renders without retries, as before
 * there was a policy, until Next is removed.
 */
function retryTransientFailure(failureCount: number, error: unknown): boolean {
  if (environmentManager.isServer()) return false;
  if (error instanceof EneoApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 3;
}

let browserQueryClient: QueryClient | undefined;

/**
 * On the server: a fresh client per call (no cross-request state). In the
 * browser: a singleton that survives suspense-driven re-renders.
 */
export function getQueryClient(): QueryClient {
  if (environmentManager.isServer()) return makeQueryClient();
  return (browserQueryClient ??= makeQueryClient());
}

/**
 * A data-driven `refetchInterval`: every `activeMs` while `isActive(data)`,
 * otherwise every `idleMs` (default: not at all), and never after a final
 * error. The data outlives an error, so without that check a deleted or
 * forbidden resource that was active would be polled for good.
 */
export function pollWhile<TData>(
  isActive: (data: TData | undefined) => boolean,
  activeMs: number,
  idleMs: number | false = false
) {
  return (query: { state: { data: TData | undefined; error: unknown } }): number | false => {
    if (isFinalError(query.state.error)) return false;
    return isActive(query.state.data) ? activeMs : idleMs;
  };
}

/*
 * How a route loader or guard reads data: three operations, never a bare
 * `queryClient.query` (whose meaning depends on the options' staleTime).
 * A failed background refetch marks a query invalidated (query-core 5.104),
 * so `isInvalidated` must never decide whether a read blocks.
 */
type ReadOptions<TQueryFnData, TError, TData, TQueryKey extends QueryKey> = QueryExecuteOptions<
  TQueryFnData,
  TError,
  TData,
  TQueryFnData,
  TQueryKey
>;

/**
 * Session and display data: what is cached, as it is, even when stale or
 * after a failed background refresh; the mounted observers refresh it. Loads,
 * and rejects on failure, only when nothing is cached.
 */
export function readCached<
  TQueryFnData,
  TError = DefaultError,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey
>(
  queryClient: QueryClient,
  options: ReadOptions<TQueryFnData, TError, TData, TQueryKey>
): Promise<TData> {
  return queryClient.query({ ...options, staleTime: "static" });
}

/**
 * A guard's evidence (may this user open this page?): read again once older
 * than the options' staleTime or invalidated, so a revoked permission or a
 * deleted resource fails now, with its 403 or 404, instead of passing on
 * cached data. Navigation waits for it, so it fails at once, without retries.
 */
export function readFresh<
  TQueryFnData,
  TError = DefaultError,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey
>(
  queryClient: QueryClient,
  options: ReadOptions<TQueryFnData, TError, TData, TQueryKey>
): Promise<TData> {
  return queryClient.query({ ...options, retry: false });
}

/**
 * Starts loading what the page will need without waiting for it. The query's
 * own retry policy applies, so a component that joins the request keeps its
 * retries (or its deliberate `retry: false`); a failure stays in the cache
 * for that component to show.
 */
export function warmQuery<
  TQueryFnData,
  TError = DefaultError,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey
>(queryClient: QueryClient, options: ReadOptions<TQueryFnData, TError, TData, TQueryKey>): void {
  queryClient.query(options).catch(() => {});
}
