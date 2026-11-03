import { queryOptions, type QueryClient, type QueryKey } from "@tanstack/react-query";
import type { EneoClient } from "./browser";
import { unwrap } from "./errors";
import type { Schema } from "./models";

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

/** `items` with conversation `id` renamed to `name`, or without it when `name` is null. */
export function patchConversations<Item extends { id: string; name: string }>(
  items: Item[],
  id: string,
  name: string | null
): Item[] {
  return name === null
    ? items.filter((item) => item.id !== id)
    : items.map((item) => (item.id === id ? { ...item, name } : item));
}

/**
 * Shows a rename (the new `name`) or a delete (`null`) in every loaded recent
 * list at once; the refetch follows.
 */
export function patchRecentConversations(
  queryClient: QueryClient,
  id: string,
  name: string | null
) {
  queryClient.setQueriesData<RecentConversation[]>(
    { queryKey: RECENT_CONVERSATIONS_KEY },
    (items) => items && patchConversations(items, id, name)
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
    invalidateRecentConversations(queryClient)
  ]);
}

/** Refetches every recent list: the SideNav's and the history's "Alla". */
export function invalidateRecentConversations(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: RECENT_CONVERSATIONS_KEY });
}
