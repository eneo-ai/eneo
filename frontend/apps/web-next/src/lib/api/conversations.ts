import {
  queryOptions,
  type InfiniteData,
  type QueryClient,
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

const RECENT_CONVERSATIONS_KEY = ["conversations", "recent"] as const;

/** The user's latest conversations with every assistant and group chat, latest activity first. */
export function recentConversationsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: RECENT_CONVERSATIONS_KEY,
    queryFn: async ({ signal }) => {
      const page = await unwrap(
        api.GET("/api/v1/conversations/recent/", {
          params: { query: { limit: RECENT_CONVERSATIONS_LIMIT } },
          signal
        })
      );
      return page.items;
    }
  });
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
 * conversation shows up in: its partner's history (`historyKey`, every loaded
 * page) and the recent list. A list that is not loaded stays unloaded; the
 * refetch `invalidateConversationLists` starts follows.
 */
export function patchConversationLists(
  queryClient: QueryClient,
  historyKey: QueryKey,
  id: string,
  name: string | null
) {
  const patch = <Item extends { id: string; name: string }>(items: Item[]) =>
    name === null
      ? items.filter((item) => item.id !== id)
      : items.map((item) => (item.id === id ? { ...item, name } : item));
  queryClient.setQueryData<InfiniteData<CursorPage<{ id: string; name: string }>>>(
    historyKey,
    (data) =>
      data && { ...data, pages: data.pages.map((page) => ({ ...page, items: patch(page.items) })) }
  );
  queryClient.setQueryData<RecentConversation[]>(
    RECENT_CONVERSATIONS_KEY,
    (data) => data && patch(data)
  );
}
