import type { UseQueryResult } from "@tanstack/react-query";
import { useState } from "react";
import { blockingError, type QueryLike } from "@/components/composites/query-state";

/**
 * A read keyed by the run's progress, as the run's page and the chat's run card show it: what it
 * last answered stays while the read of a newer version is pending or has failed
 * (`keepPreviousData` keeps it only while pending), and a failure beside it is a failed refresh
 * (`RefreshError`) until a read answers, its retry included: React Query reports the retry of a
 * read with nothing of its own as pending, without its error, which would take the refresh error,
 * and its button under focus, away.
 */
export function useShownRead<T>(read: UseQueryResult<T>): QueryLike<T> & { failureCount: number } {
  const [last, setLast] = useState(read.data);
  if (read.data !== undefined && read.data !== last) setLast(read.data);
  return {
    data: read.data ?? last,
    isPending: read.isPending,
    isError: read.isError || blockingError(read),
    error: read.error,
    isFetching: read.isFetching,
    fetchStatus: read.fetchStatus,
    errorUpdatedAt: read.errorUpdatedAt,
    dataUpdatedAt: read.dataUpdatedAt,
    failureCount: read.failureCount,
    refetch: read.refetch
  };
}
