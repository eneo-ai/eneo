"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { CursorPage } from "@/lib/api/pagination";

/**
 * Page-by-page navigation over a cursor-paginated endpoint. Keeps a stack of
 * visited cursors so "previous" works without the backend's previous_cursor.
 * Reset (e.g. on filter change) by changing the queryKey.
 */
export function usePaginatedQuery<TItem>({
  queryKey,
  fetchPage,
  limit = 50
}: {
  queryKey: readonly unknown[];
  fetchPage: (params: { cursor?: string; limit: number }) => Promise<CursorPage<TItem>>;
  limit?: number;
}) {
  // The stack is bound to the queryKey: when the key changes (filter change),
  // pagination restarts from the first page.
  const keyHash = JSON.stringify(queryKey);
  const [pages, setPages] = useState<{ key: string; stack: string[] }>({
    key: keyHash,
    stack: []
  });
  const cursorStack = pages.key === keyHash ? pages.stack : [];
  const cursor = cursorStack[cursorStack.length - 1];

  const query = useQuery({
    queryKey: [...queryKey, { cursor, limit }],
    queryFn: () => fetchPage({ cursor, limit }),
    placeholderData: keepPreviousData
  });

  const nextCursor = query.data?.next_cursor ?? undefined;

  return {
    ...query,
    items: query.data?.items ?? [],
    totalCount: query.data?.total_count,
    hasNextPage: nextCursor !== undefined && nextCursor !== null,
    hasPreviousPage: cursorStack.length > 0,
    nextPage: () => {
      if (nextCursor) setPages({ key: keyHash, stack: [...cursorStack, nextCursor] });
    },
    previousPage: () => setPages({ key: keyHash, stack: cursorStack.slice(0, -1) }),
    resetPages: () => setPages({ key: keyHash, stack: [] })
  };
}
