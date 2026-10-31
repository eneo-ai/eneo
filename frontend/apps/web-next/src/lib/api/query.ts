import {
  QueryClient,
  type DefaultError,
  type QueryExecuteOptions,
  type QueryKey
} from "@tanstack/react-query";
import { EneoApiError, isFinalError } from "./errors";

/**
 * Shared cache and retry defaults for route loaders and mounted components.
 *
 * Query key convention: keys mirror backend resource paths —
 * ["dashboard"], ["spaces", spaceId], ["spaces", spaceId, "applications"].
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Reuse recently loaded data across route and component readers.
        staleTime: 30_000,
        retry: retryTransientFailure
      }
    }
  });
}

/**
 * The default retry policy (a query with its own `retry` keeps it): a refusal
 * (4xx) is final, asking again won't change it; a server or network failure
 * is tried three more times.
 */
function retryTransientFailure(failureCount: number, error: unknown): boolean {
  if (error instanceof EneoApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 3;
}

let browserQueryClient: QueryClient | undefined;

/**
 * One client per document, surviving suspense-driven re-renders.
 */
export function getQueryClient(): QueryClient {
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
 * so `isInvalidated` must never decide whether a read blocks. None of them
 * changes `retry`: a query keeps the options of the request that started
 * it, so a reader's own retry would reach every other reader.
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
 * cached data. Retries follow the resource's options, which every reader of
 * the query shares: a resource whose guard must fail at once says
 * `retry: false` there.
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
  return queryClient.query(options);
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
