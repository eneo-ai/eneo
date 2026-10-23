/**
 * Helpers for the backend's cursor-paginated list shape
 * (CursorPaginatedResponse: items + total_count + next/previous cursor).
 *
 * RB-5: this is the canonical list contract. Endpoints that still use offset
 * pagination (/admin/users/, audit logs) get per-endpoint wrappers marked
 * `// RB-5(x)` instead of support here.
 */

export interface CursorPage<T> {
  items: T[];
  total_count: number;
  limit?: number | null;
  next_cursor?: string | null;
  previous_cursor?: string | null;
}

/** `getNextPageParam` for useInfiniteQuery over a cursor-paginated endpoint. */
export function nextPageCursor(lastPage: CursorPage<unknown>): string | undefined {
  return lastPage.next_cursor ?? undefined;
}

/** Flattens infinite-query pages into a single item list. */
export function flattenPages<T>(pages: CursorPage<T>[] | undefined): T[] {
  return pages?.flatMap((page) => page.items) ?? [];
}

/**
 * Shared useInfiniteQuery options for cursor-paginated endpoints; spread into
 * infiniteQueryOptions({...cursorPagination, queryKey, queryFn}).
 */
export const cursorPagination = {
  initialPageParam: undefined as string | undefined,
  getNextPageParam: nextPageCursor
};
