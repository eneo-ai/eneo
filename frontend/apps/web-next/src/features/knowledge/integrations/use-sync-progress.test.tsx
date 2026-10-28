// @vitest-environment jsdom
import { act } from "@testing-library/react";
import { focusManager, type QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import type { IntegrationSyncProgress } from "./sync-progress";

const state = vi.hoisted(() => ({ space: null as unknown }));
const api = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { pendingSyncs, resetPendingSyncs, trackSyncs } from "./pending-syncs";
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

/** Lets React Query hand out its batched notifications; fake timers must move for that. */
async function flush(ms = 20) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const progressPolls = () => api.GET.mock.calls.length;

beforeEach(() => {
  vi.useFakeTimers();
  state.space = makeSpace({ integrations: [makeIntegration({ id: "i1" })] });
  // The poll answers that nothing runs; tests put running syncs into the cache.
  api.GET.mockImplementation(() =>
    Promise.resolve({ data: { items: [] }, response: new Response("{}") })
  );
});

afterEach(() => {
  resetPendingSyncs();
  focusManager.setFocused(undefined);
  vi.useRealTimers();
  api.GET.mockReset();
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
  it("refreshes the space once when a running sync is gone", async () => {
    const { queryClient, spaceRefreshes } = renderSyncProgress();
    await flush();

    await runAndFinish(queryClient);
    expect(spaceRefreshes()).toBe(1);

    // The progress is cleared after the sync's commit: one refresh reads it.
    await flush(5_000);
    expect(spaceRefreshes()).toBe(1);
  });

  it("does not poll a space without integration knowledge of its own", async () => {
    // A source shared in from another space syncs there.
    state.space = makeSpace({ integrations: [makeIntegration({ id: "i1", space_id: "space-0" })] });
    const { result } = renderSyncProgress();

    await flush(60_000);
    expect(progressPolls()).toBe(0);
    expect(result.current.progress).toEqual({});
  });

  it("polls a space with integration knowledge, but not while the browser tab is hidden", async () => {
    renderSyncProgress();
    await flush();
    expect(progressPolls()).toBe(1);
    await flush(15_000);
    expect(progressPolls()).toBe(2);

    act(() => focusManager.setFocused(false));
    await flush(60_000);
    expect(progressPolls()).toBe(2);

    // Shown again, the stale progress is read at once.
    act(() => focusManager.setFocused(true));
    await flush();
    expect(progressPolls()).toBe(3);
  });

  it("polls fast for a sync queued from here until its worker reports, then lets progress tell", async () => {
    const { result } = renderSyncProgress();
    await flush();
    expect(progressPolls()).toBe(1);

    act(() => trackSyncs([{ jobId: "job-1", knowledgeId: "i1" }]));
    expect(result.current.queued).toEqual(new Set(["i1"]));
    await flush(2_000);
    expect(progressPolls()).toBe(2);
    await flush(2_000);
    expect(progressPolls()).toBe(3);

    api.GET.mockImplementation(() =>
      Promise.resolve({ data: { items: [running("i1")] }, response: new Response("{}") })
    );
    await flush(2_000);
    await flush();
    expect(Object.keys(result.current.progress)).toEqual(["i1"]);
    expect(result.current.queued.size).toBe(0);
    expect(pendingSyncs()).toEqual([]);
  });

  it("keeps a full sync queued while a change notification's delta pass of the item runs", async () => {
    const { result } = renderSyncProgress();
    await flush();
    act(() => trackSyncs([{ jobId: "job-1", knowledgeId: "i1" }]));
    api.GET.mockImplementation(() =>
      Promise.resolve({
        data: { items: [{ ...running("i1"), sync_type: "delta" }] },
        response: new Response("{}")
      })
    );
    await flush(2_000);
    await flush();
    expect(Object.keys(result.current.progress)).toEqual(["i1"]);
    expect(result.current.queued).toEqual(new Set(["i1"]));
    expect(pendingSyncs()).toEqual([{ jobId: "job-1", knowledgeId: "i1" }]);
  });

  it.each([401, 403, 404])("stops polling for good on a %i", async (status) => {
    api.GET.mockImplementation(() =>
      Promise.resolve({ error: { detail: "No" }, response: new Response("{}", { status }) })
    );
    renderSyncProgress();
    await flush();
    expect(progressPolls()).toBe(1);
    await flush(60_000);
    expect(progressPolls()).toBe(1);
  });

  it("does not poll fast for a sync queued in another space", async () => {
    const { result } = renderSyncProgress();
    await flush();

    act(() => trackSyncs([{ jobId: "job-9", knowledgeId: "elsewhere" }]));
    await flush(14_000);
    expect(progressPolls()).toBe(1);
    expect(result.current.queued.size).toBe(0);
  });
});
