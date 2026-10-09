import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function event(permissions: string[]) {
  const policy = { max_daily_token_budget: 5000 };
  const get = vi.fn().mockResolvedValue(policy);
  return {
    get,
    policy,
    event: {
      params: { spaceId: "space-1", assistantId: "assistant-1" },
      data: { release: null },
      parent: vi.fn().mockResolvedValue({
        user: { roles: [{ permissions }], predefined_roles: [] },
        currentSpace: { id: "space-1" },
        eneo: {
          assistants: { get: vi.fn().mockResolvedValue({ id: "assistant-1" }) },
          widgets: {
            list: vi.fn().mockResolvedValue([]),
            policy: { get },
            templates: { list: vi.fn().mockResolvedValue([]) }
          }
        }
      })
    }
  };
}

describe("assistant widget loader", () => {
  test("an editor with the widgets permission gets the organisation's policy too", async () => {
    const { event: loadEvent, get, policy } = event(["widgets"]);
    const result = await load(loadEvent as never);
    expect(get).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ isAdmin: false, policy });
  });

  test("an unreadable policy leaves the server to enforce it", async () => {
    const { event: loadEvent, get } = event(["widgets", "admin"]);
    get.mockRejectedValueOnce(new Error("forbidden"));
    const result = await load(loadEvent as never);
    expect(result).toMatchObject({ isAdmin: true, policy: null });
  });
});
