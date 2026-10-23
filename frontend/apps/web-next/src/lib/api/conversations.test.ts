import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "./browser";
import {
  invalidateConversationLists,
  RECENT_CONVERSATIONS_LIMIT,
  recentConversationsQueryOptions
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
