import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "./browser";
import {
  ALL_CONVERSATIONS_LIMIT,
  dropFromRecentConversations,
  invalidateConversationLists,
  RECENT_CONVERSATIONS_LIMIT,
  recentConversationsQueryOptions,
  type RecentConversation
} from "./conversations";
import { makeQueryClient } from "./query";

afterEach(() => vi.restoreAllMocks());

const ok = (data: unknown) =>
  Promise.resolve({ data, error: undefined, response: new Response("{}", { status: 200 }) });

describe("recentConversationsQueryOptions", () => {
  it("loads the user's latest conversations across partners", async () => {
    const items = [{ id: "c1" }, { id: "c2" }];
    const get = vi
      .spyOn(browserApi, "GET")
      .mockImplementation((() => ok({ items, count: 2 })) as unknown as typeof browserApi.GET);

    const conversations = await makeQueryClient().query(
      recentConversationsQueryOptions(browserApi)
    );

    expect(conversations).toEqual(items);
    expect(get).toHaveBeenCalledWith("/api/v1/conversations/recent/", {
      params: { query: { limit: RECENT_CONVERSATIONS_LIMIT } },
      signal: expect.any(AbortSignal)
    });
  });
});

describe("invalidateConversationLists", () => {
  it("refreshes the partner's history and the recent list, nothing else", async () => {
    const queryClient = makeQueryClient();
    const history = ["conversations", "assistant", "a1"];
    const otherHistory = ["conversations", "group-chat", "g1"];
    const recent = recentConversationsQueryOptions(browserApi).queryKey;
    const detail = ["conversations", "detail", "c1"];
    for (const key of [history, otherHistory, recent, detail]) {
      queryClient.setQueryData(key, []);
    }

    await invalidateConversationLists(queryClient, history);

    const invalidated = (key: readonly unknown[]) =>
      queryClient.getQueryState(key)?.isInvalidated ?? false;
    expect(invalidated(history)).toBe(true);
    expect(invalidated(recent)).toBe(true);
    expect(invalidated(otherHistory)).toBe(false);
    expect(invalidated(detail)).toBe(false);
  });
});

describe("dropFromRecentConversations", () => {
  it("drops a deleted conversation from every recent list, the SideNav's and Alla", () => {
    const queryClient = makeQueryClient();
    const nav = recentConversationsQueryOptions(browserApi).queryKey;
    const all = recentConversationsQueryOptions(browserApi, ALL_CONVERSATIONS_LIMIT).queryKey;
    const rows = [{ id: "c1" }, { id: "c2" }] as RecentConversation[];
    for (const key of [nav, all]) queryClient.setQueryData(key, rows);

    dropFromRecentConversations(queryClient, "c1");

    expect(queryClient.getQueryData(nav)).toEqual([{ id: "c2" }]);
    expect(queryClient.getQueryData(all)).toEqual([{ id: "c2" }]);
  });
});
