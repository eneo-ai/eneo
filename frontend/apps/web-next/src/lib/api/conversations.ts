import {
  queryOptions,
  type InfiniteData,
  type QueryClient,
  type QueryFilters,
  type QueryKey
} from "@tanstack/react-query";
import type { EneoClient } from "./browser";
import { unwrap } from "./errors";
import type { Schema } from "./models";
import type { CursorPage } from "./pagination";

export type RecentConversation = Schema<"RecentConversation">;

/**
 * How many recent conversations the app loads. One list serves both the
 * SideNav, which shows the first few under "Senaste", and the ⌘K palette,
 * which searches them all.
 */
export const RECENT_CONVERSATIONS_LIMIT = 20;
/** The most the endpoint returns: what the history's "Alla" lists. */
export const ALL_CONVERSATIONS_LIMIT = 50;

const RECENT_CONVERSATIONS_KEY = ["conversations", "recent"] as const;

/**
 * The user's latest `limit` conversations with every assistant and group
 * chat, latest activity first.
 */
export function recentConversationsQueryOptions(
  api: EneoClient,
  limit = RECENT_CONVERSATIONS_LIMIT
) {
  return queryOptions({
    queryKey: [...RECENT_CONVERSATIONS_KEY, limit],
    queryFn: async ({ signal }) => {
      const page = await unwrap(
        api.GET("/api/v1/conversations/recent/", { params: { query: { limit } }, signal })
      );
      return page.items;
    }
  });
}

/** Drops a deleted conversation from every recent list at once; the refetch follows. */
export function dropFromRecentConversations(queryClient: QueryClient, id: string) {
  queryClient.setQueriesData<RecentConversation[]>(
    { queryKey: RECENT_CONVERSATIONS_KEY },
    (items) => items?.filter((item) => item.id !== id)
  );
}

/**
 * Refetches every list a conversation shows up in after it was started,
 * answered, renamed or deleted: its partner's history (`historyKey`) and the
 * recent list across all partners.
 */
export function invalidateConversationLists(queryClient: QueryClient, historyKey: QueryKey) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: historyKey }),
    queryClient.invalidateQueries({ queryKey: RECENT_CONVERSATIONS_KEY })
  ]);
}

/**
 * Shows a rename (the new `name`) or a delete (`null`) at once in the lists a
 * conversation shows up in: its partner's history (`historyFilters`, every loaded
 * page) and the recent list. A list that is not loaded stays unloaded; the
 * refetch `invalidateConversationLists` starts follows.
 */
export function patchConversationLists(
  queryClient: QueryClient,
  historyFilters: QueryFilters,
  id: string,
  name: string | null
) {
  const patch = <Item extends { id: string; name: string }>(items: Item[]) =>
    name === null
      ? items.filter((item) => item.id !== id)
      : items.map((item) => (item.id === id ? { ...item, name } : item));
  queryClient.setQueriesData<InfiniteData<CursorPage<{ id: string; name: string }>>>(
    historyFilters,
    (data) =>
      data && { ...data, pages: data.pages.map((page) => ({ ...page, items: patch(page.items) })) }
  );
  queryClient.setQueriesData<RecentConversation[]>(
    { queryKey: RECENT_CONVERSATIONS_KEY },
    (data) => data && patch(data)
  );
}
