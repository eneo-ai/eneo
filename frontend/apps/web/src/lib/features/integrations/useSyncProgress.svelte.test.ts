import { writable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IntegrationSyncProgress } from "./syncProgress";

const api = vi.hoisted(() => ({
  getSyncProgress: vi.fn(),
  refreshCurrentSpace: vi.fn()
}));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ integrations: { knowledge: { getSyncProgress: api.getSyncProgress } } })
}));

function spaceWith(itemIds: string[]) {
  return {
    id: "space-1",
    knowledge: { integrationKnowledge: itemIds.map((id) => ({ id, space_id: "space-1" })) }
  };
}

const currentSpace = writable(spaceWith(["a"]));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: { currentSpace },
    refreshCurrentSpace: api.refreshCurrentSpace
  })
}));

import SyncProgressTestHost from "./SyncProgressTestHost.svelte";

function entry(id: string): IntegrationSyncProgress {
  return {
    integration_knowledge_id: id,
    sync_type: "delta",
    phase: "processing",
    started_at: "2026-10-15T10:00:00Z",
    updated_at: "2026-10-15T10:00:01Z",
    total: null,
    done: 1,
    indexed: 1,
    unchanged: 0,
    skipped: 0,
    deleted: 0
  };
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("useSyncProgress", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    currentSpace.set(spaceWith(["a"]));
    api.getSyncProgress.mockReset().mockResolvedValue({ items: [] });
    api.refreshCurrentSpace.mockReset().mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (document as { hidden?: boolean }).hidden;
  });

  it("polls only for a space with integration knowledge, while active and visible", async () => {
    // Knowledge another space shares is not this space's to sync.
    currentSpace.set({
      id: "space-1",
      knowledge: { integrationKnowledge: [{ id: "shared", space_id: "space-2" }] }
    });
    const { rerender, unmount } = render(SyncProgressTestHost, { active: true });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(api.getSyncProgress).not.toHaveBeenCalled();

    currentSpace.set(spaceWith(["a"]));
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getSyncProgress).toHaveBeenCalledTimes(1);

    await rerender({ active: false });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(api.getSyncProgress).toHaveBeenCalledTimes(1);

    await rerender({ active: true });
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getSyncProgress).toHaveBeenCalledTimes(2);

    setHidden(true);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(api.getSyncProgress).toHaveBeenCalledTimes(2);

    // Coming back polls at once rather than at the next interval.
    setHidden(false);
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getSyncProgress).toHaveBeenCalledTimes(3);
    unmount();
  });

  it("looks for new progress as soon as the space changes", async () => {
    const { unmount } = render(SyncProgressTestHost);
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getSyncProgress).toHaveBeenCalledTimes(1);

    currentSpace.set(spaceWith(["a", "b"]));
    await vi.advanceTimersByTimeAsync(0);
    expect(api.getSyncProgress).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("refreshes the space once when a sync finishes", async () => {
    api.getSyncProgress.mockResolvedValueOnce({ items: [entry("a")] });
    const { unmount } = render(SyncProgressTestHost);
    await vi.advanceTimersByTimeAsync(0);
    expect(api.refreshCurrentSpace).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(2_000);
    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(1);
    expect(api.refreshCurrentSpace).toHaveBeenCalledWith("knowledge");
    // The progress is cleared after the sync commits, so one refresh is enough.
    await vi.advanceTimersByTimeAsync(10_000);
    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(1);
    unmount();
  });

  it("stops polling when unmounted", async () => {
    api.getSyncProgress.mockResolvedValueOnce({ items: [entry("a")] });
    const { unmount } = render(SyncProgressTestHost);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(1);
    const polls = api.getSyncProgress.mock.calls.length;

    unmount();
    await vi.advanceTimersByTimeAsync(60_000);

    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(1);
    expect(api.getSyncProgress).toHaveBeenCalledTimes(polls);
  });
});
