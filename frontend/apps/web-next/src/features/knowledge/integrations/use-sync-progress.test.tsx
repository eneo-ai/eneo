// @vitest-environment jsdom
import { act } from "@testing-library/react";
import type { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import type { IntegrationSyncProgress } from "./sync-progress";

const state = vi.hoisted(() => ({ space: null as unknown }));

vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
// The progress is put into the cache by the test; the poll itself never answers.
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: () => new Promise(() => {}) } }));

import { useSyncProgress } from "./use-sync-progress";

const PROGRESS_KEY = ["integrations", "sync-progress", "space-1"];

function running(id: string): IntegrationSyncProgress {
  return {
    integration_knowledge_id: id,
    sync_type: "full",
    phase: "processing",
    started_at: "2026-10-15T10:00:00Z",
    updated_at: "2026-10-15T10:01:00Z",
    total: 10,
    done: 4,
    indexed: 4,
    unchanged: 0,
    skipped: 0,
    deleted: 0
  };
}

function spaceWith(syncedAt: string) {
  return makeSpace({
    integrations: [
      makeIntegration({
        id: "i1",
        metadata: { size: 0, last_synced_at: syncedAt, last_sync_attempted_at: syncedAt }
      }),
      makeIntegration({
        id: "i2",
        metadata: { size: 0, last_synced_at: "2026-10-01T08:00:00Z" }
      })
    ]
  });
}

/** The lists of an item that a finished sync makes stale, seeded so their state can be read. */
function listKeys(itemId: string) {
  return [
    [
      "integrations",
      "documents",
      "space-1",
      itemId,
      { q: "", sort: "path", order: "asc", page: 1 }
    ],
    ["integrations", "skipped", "space-1", itemId],
    ["integrations", "sync-logs", itemId, "recent", 20]
  ];
}

function seedLists(queryClient: QueryClient) {
  for (const itemId of ["i1", "i2"]) {
    for (const key of listKeys(itemId)) queryClient.setQueryData(key, { items: [] });
  }
}

const isInvalidated = (queryClient: QueryClient, key: unknown[]) =>
  queryClient.getQueryState(key)?.isInvalidated ?? false;

/**
 * Lets React Query hand out its batched notifications and the space refetch
 * settle. A zero-delay timer set while fake timers tick is due a millisecond
 * later, so the clock has to move.
 */
async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  state.space = spaceWith("2026-10-14T08:00:00Z");
});

afterEach(() => {
  vi.useRealTimers();
});

function renderSyncProgress() {
  const rendered = renderHookInApp(() => useSyncProgress());
  const invalidate = vi.spyOn(rendered.queryClient, "invalidateQueries");
  const spaceRefreshes = () =>
    invalidate.mock.calls.filter(
      ([filters]) => JSON.stringify(filters?.queryKey) === JSON.stringify(["spaces", "space-1"])
    ).length;
  return { ...rendered, spaceRefreshes };
}

async function runAndFinish(queryClient: QueryClient) {
  act(() => queryClient.setQueryData(PROGRESS_KEY, { i1: running("i1") }));
  await flush();
  act(() => queryClient.setQueryData(PROGRESS_KEY, {}));
  await flush();
}

describe("useSyncProgress", () => {
  it("refreshes the space when a running sync is gone, and once more 3 s later", async () => {
    const { queryClient, spaceRefreshes } = renderSyncProgress();
    await flush();

    await runAndFinish(queryClient);
    expect(spaceRefreshes()).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(spaceRefreshes()).toBe(2);
  });

  it("refetches the finished item's lists once the space shows its new sync, and no one else's", async () => {
    const { queryClient } = renderSyncProgress();
    seedLists(queryClient);
    await flush();

    // The refreshed space carries the sync's commit.
    state.space = spaceWith("2026-10-15T10:05:00Z");
    await runAndFinish(queryClient);

    for (const key of listKeys("i1")) expect(isInvalidated(queryClient, key)).toBe(true);
    for (const key of listKeys("i2")) expect(isInvalidated(queryClient, key)).toBe(false);
  });

  it("leaves the lists alone while the space still shows the old sync", async () => {
    const { queryClient } = renderSyncProgress();
    seedLists(queryClient);
    await flush();

    await runAndFinish(queryClient);
    for (const key of listKeys("i1")) expect(isInvalidated(queryClient, key)).toBe(false);
  });

  it("drops the pending recheck when it unmounts", async () => {
    const { queryClient, spaceRefreshes, unmount } = renderSyncProgress();
    await flush();
    await runAndFinish(queryClient);
    expect(spaceRefreshes()).toBe(1);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(spaceRefreshes()).toBe(1);
  });
});
