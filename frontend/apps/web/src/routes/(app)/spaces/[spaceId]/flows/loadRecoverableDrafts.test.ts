import { afterEach, describe, expect, it, vi } from "vitest";
import type { Role } from "@eneo/eneo-js";

import { AI_DRAFTS_TIMEOUT_MS, loadRecoverableDrafts } from "./loadRecoverableDrafts";

const SPACE_ID = "space-1";

function makeUser(permissions: string[]): { roles: Role[] } {
  return { roles: [{ permissions } as unknown as Role] };
}

const builderUser = makeUser(["flows_manage", "flows_ai_builder"]);

function makeSession(overrides: Record<string, unknown> = {}) {
  return {
    session_id: "draft-1",
    space_id: SPACE_ID,
    status: "awaiting_approval",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: "plan-1",
    draft_title: "Sammanfatta till PDF",
    created_at: "2026-07-13T08:00:00Z",
    updated_at: "2026-07-13T08:05:00Z",
    ...overrides
  };
}

function makeEneo(
  fetchImpl: (endpoint: unknown, init?: { signal?: AbortSignal }) => Promise<unknown>
) {
  return { client: { fetch: fetchImpl } } as unknown as Parameters<
    typeof loadRecoverableDrafts
  >[0]["eneo"];
}

afterEach(() => {
  vi.useRealTimers();
});

describe("loadRecoverableDrafts", () => {
  it("does not call the endpoint without both builder permissions", async () => {
    const fetch = vi.fn();
    for (const user of [makeUser(["flows_manage"]), makeUser(["flows_ai_builder"]), makeUser([])]) {
      const drafts = await loadRecoverableDrafts({
        eneo: makeEneo(fetch),
        currentSpace: { id: SPACE_ID },
        user
      });
      expect(drafts).toEqual([]);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps only recoverable create drafts in the current space", async () => {
    const sessions = [
      makeSession(),
      makeSession({ session_id: "chatting", status: "chatting", latest_plan_id: null }),
      makeSession({ session_id: "applied", status: "applied" }),
      makeSession({ session_id: "cancelled", status: "cancelled" }),
      makeSession({ session_id: "foreign", space_id: "other-space" }),
      makeSession({ session_id: "edit", target_kind: "edit", flow_id: "flow-9" }),
      makeSession({ session_id: "flow-bound", flow_id: "flow-3" })
    ];
    const drafts = await loadRecoverableDrafts({
      eneo: makeEneo(async () => ({ sessions })),
      currentSpace: { id: SPACE_ID },
      user: builderUser
    });
    expect(drafts.map((d) => d.session_id)).toEqual(["draft-1", "chatting"]);
  });

  it("returns no drafts when the endpoint fails", async () => {
    const drafts = await loadRecoverableDrafts({
      eneo: makeEneo(async () => {
        throw new Error("boom");
      }),
      currentSpace: { id: SPACE_ID },
      user: builderUser
    });
    expect(drafts).toEqual([]);
  });

  it("aborts the request at the latency budget instead of delaying the page", async () => {
    vi.useFakeTimers();
    let receivedSignal: AbortSignal | undefined;
    const fetch = vi.fn((_endpoint: unknown, init?: { signal?: AbortSignal }) => {
      receivedSignal = init?.signal;
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
      });
    });
    const pending = loadRecoverableDrafts({
      eneo: makeEneo(fetch),
      currentSpace: { id: SPACE_ID },
      user: builderUser
    });
    await vi.advanceTimersByTimeAsync(AI_DRAFTS_TIMEOUT_MS + 1);
    await expect(pending).resolves.toEqual([]);
    // The deadline must CANCEL the request, not orphan it server-side.
    expect(receivedSignal?.aborted).toBe(true);
  });
});
