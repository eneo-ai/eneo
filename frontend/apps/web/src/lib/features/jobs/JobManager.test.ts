import type { Eneo, Job } from "@eneo/eneo-js";
import { get } from "svelte/store";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("$app/environment", () => ({ browser: true }));
vi.mock("$app/navigation", () => ({ invalidate: vi.fn() }));
vi.mock("$lib/components/toast", () => ({ toast: { error: vi.fn() } }));
vi.mock("$lib/core/context", () => ({
  createContext: <T>() => {
    let value: T;
    return [
      () => value,
      (next: T) => {
        value = next;
      }
    ];
  }
}));

import { getJobManager, initJobManager, jobCompletionEvents } from "./JobManager";

const listJobs = vi.fn();
beforeEach(() => {
  vi.useFakeTimers();
  listJobs.mockReset().mockResolvedValue([]);
  jobCompletionEvents.set(null);
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

it("counts every crawl after restarting idle polling and refreshes failed outcomes", async () => {
  initJobManager({ eneo: { jobs: { list: listJobs } } as unknown as Eneo });
  const manager = getJobManager();
  await vi.advanceTimersByTimeAsync(30_000);
  const active = Array.from(
    { length: 3 },
    (_, index) =>
      ({
        id: `job-${index}`,
        task: "crawl",
        status: "queued"
      }) as Job
  );
  listJobs.mockResolvedValue(active);
  await manager.startFastUpdatePolling();
  expect(get(manager.state.currentlyRunningJobs)).toBe(3);

  listJobs.mockResolvedValue(
    active.map((job) => ({
      ...job,
      status: "failed",
      failure_code: "tenant_quota_exceeded"
    }))
  );
  await vi.advanceTimersByTimeAsync(2_000);
  expect(get(manager.state.currentlyRunningJobs)).toBe(0);
  expect(get(jobCompletionEvents)).not.toBeNull();
});
