import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyncProgressTracker } from "./SyncProgressTracker.svelte";
import type { IntegrationSyncProgress } from "./syncProgress";

function entry(id: string): IntegrationSyncProgress {
  return {
    integration_knowledge_id: id,
    sync_type: "full",
    phase: "processing",
    started_at: "2026-10-14T10:00:00Z",
    updated_at: "2026-10-14T10:00:01Z",
    total: null,
    done: 1,
    indexed: 1,
    unchanged: 0,
    skipped: 0,
    deleted: 0
  };
}

describe("SyncProgressTracker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls fast while something syncs, slowly after, and reports what finished", async () => {
    const responses = [[entry("a"), entry("b")], [entry("b")], []];
    const load = vi.fn(async () => ({ items: responses.shift() ?? [] }));
    const onSettled = vi.fn();
    const tracker = new SyncProgressTracker({ load, onSettled });

    tracker.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(Object.keys(tracker.byId)).toEqual(["a", "b"]);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(onSettled).toHaveBeenLastCalledWith(["a"]);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(tracker.active).toBe(false);
    expect(onSettled).toHaveBeenLastCalledWith(["b"]);

    await vi.advanceTimersByTimeAsync(14_000);
    expect(load).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(load).toHaveBeenCalledTimes(4);
    tracker.stop();
  });

  it("keeps the same object while nothing changes, so readers do not re-render", async () => {
    const load = vi.fn(async () => ({ items: [] as IntegrationSyncProgress[] }));
    const tracker = new SyncProgressTracker({ load });

    tracker.start();
    await vi.advanceTimersByTimeAsync(0);
    const first = tracker.byId;
    await vi.advanceTimersByTimeAsync(15_000);

    expect(load).toHaveBeenCalledTimes(2);
    expect(tracker.byId).toBe(first);
    tracker.stop();
  });

  it("stops for good when the backend has no progress endpoint", async () => {
    const load = vi.fn(async () => {
      throw Object.assign(new Error("Not found"), { status: 404 });
    });
    const tracker = new SyncProgressTracker({ load });

    tracker.start();
    await vi.advanceTimersByTimeAsync(60_000);
    tracker.refresh();
    await vi.advanceTimersByTimeAsync(0);

    expect(load).toHaveBeenCalledTimes(1);
  });

  it("drops a response that arrives after it was stopped", async () => {
    let resolve: (value: { items: IntegrationSyncProgress[] }) => void = () => {};
    const load = vi.fn(
      () => new Promise<{ items: IntegrationSyncProgress[] }>((done) => (resolve = done))
    );
    const tracker = new SyncProgressTracker({ load });

    tracker.start();
    tracker.stop();
    resolve({ items: [entry("a")] });
    await vi.advanceTimersByTimeAsync(10_000);

    expect(tracker.byId).toEqual({});
    expect(load).toHaveBeenCalledTimes(1);
  });
});
