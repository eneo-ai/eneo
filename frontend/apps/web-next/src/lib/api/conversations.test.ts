import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "./browser";
import {
  ALL_CONVERSATIONS_LIMIT,
  dropFromRecentConversations,
  invalidateConversationLists,
  patchConversationLists,
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

const recentRow = (id: string, name: string): RecentConversation => ({
  id,
  name,
  created_at: "2026-10-26T09:00:00Z",
  last_activity_at: "2026-10-26T10:00:00Z",
  partner: { id: "assistant-1", name: "Upphandlingsassistenten", type: "assistant" },
  space: { id: "space-1", name: "Upphandling", organization: false, personal: false }
});

describe("patchConversationLists", () => {
  const history = ["conversations", "assistant", "a1"];
  const recent = recentConversationsQueryOptions(browserApi).queryKey;
  const row = (id: string, name: string) => ({ id, name, updated_at: "2026-10-26T10:00:00Z" });

  function loaded() {
    const queryClient = makeQueryClient();
    queryClient.setQueryData(history, {
      pages: [
        { items: [row("c1", "Budget"), row("c2", "Protokoll")], total_count: 3, next_cursor: "2" },
        { items: [row("c3", "Avtal")], total_count: 3, next_cursor: null }
      ],
      pageParams: [null, "2"]
    });
    queryClient.setQueryData(recent, [recentRow("c3", "Avtal"), recentRow("c9", "Annan")]);
    return queryClient;
  }

  it("shows a new name in every loaded page of the history and in the recent list", () => {
    const queryClient = loaded();
    patchConversationLists(queryClient, { queryKey: history }, "c3", "Ramavtal");
    expect(queryClient.getQueryData(history)).toEqual({
      pages: [
        { items: [row("c1", "Budget"), row("c2", "Protokoll")], total_count: 3, next_cursor: "2" },
        { items: [row("c3", "Ramavtal")], total_count: 3, next_cursor: null }
      ],
      pageParams: [null, "2"]
    });
    expect(queryClient.getQueryData(recent)).toEqual([
      recentRow("c3", "Ramavtal"),
      recentRow("c9", "Annan")
    ]);
  });

  it("drops a deleted conversation from both lists", () => {
    const queryClient = loaded();
    patchConversationLists(queryClient, { queryKey: history }, "c3", null);
    const pages = queryClient.getQueryData<{ pages: { items: unknown[] }[] }>(history)!.pages;
    expect(pages.map((page) => page.items)).toEqual([
      [row("c1", "Budget"), row("c2", "Protokoll")],
      []
    ]);
    expect(queryClient.getQueryData(recent)).toEqual([recentRow("c9", "Annan")]);
  });

  it("leaves a list that is not loaded unloaded", () => {
    const queryClient = makeQueryClient();
    patchConversationLists(queryClient, { queryKey: history }, "c3", "Ramavtal");
    expect(queryClient.getQueryState(history)).toBeUndefined();
    expect(queryClient.getQueryState(recent)).toBeUndefined();
  });
});
