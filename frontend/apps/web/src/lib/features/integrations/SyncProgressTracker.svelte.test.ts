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

  it("polls fast while a queued sync waits for its worker", async () => {
    const responses: IntegrationSyncProgress[][] = [[], [], [entry("a")], []];
    const load = vi.fn(async () => ({ items: responses.shift() ?? [] }));
    const tracker = new SyncProgressTracker({ load });

    tracker.start();
    await vi.advanceTimersByTimeAsync(0);
    tracker.pending = ["a"];
    expect([...tracker.queued]).toEqual(["a"]);
    tracker.refresh();
    await vi.advanceTimersByTimeAsync(0);
    expect(load).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(load).toHaveBeenCalledTimes(3);
    // Reported: no longer queued, still fast while it runs.
    expect(tracker.queued.size).toBe(0);
    expect(tracker.active).toBe(true);
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

  it.each([404, 403])("stops for good on a %s", async (status) => {
    const load = vi.fn(async () => {
      throw Object.assign(new Error("Refused"), { status });
    });
    const tracker = new SyncProgressTracker({ load });

    tracker.start();
    await vi.advanceTimersByTimeAsync(60_000);
    tracker.refresh();
    tracker.start();
    await vi.advanceTimersByTimeAsync(60_000);

    expect(load).toHaveBeenCalledTimes(1);
  });

  it("keeps polling through a failure that may pass", async () => {
    const load = vi.fn(async () => {
      throw Object.assign(new Error("Bad gateway"), { status: 502 });
    });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const tracker = new SyncProgressTracker({ load });

    tracker.start();
    await vi.advanceTimersByTimeAsync(30_000);

    expect(load.mock.calls.length).toBeGreaterThan(1);
    tracker.stop();
    warn.mockRestore();
  });

  it("polls at once when started again after a pause", async () => {
    const load = vi.fn(async () => ({ items: [] as IntegrationSyncProgress[] }));
    const tracker = new SyncProgressTracker({ load });

    tracker.start();
    await vi.advanceTimersByTimeAsync(0);
    tracker.stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(load).toHaveBeenCalledTimes(1);

    tracker.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(load).toHaveBeenCalledTimes(2);
    tracker.stop();
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
