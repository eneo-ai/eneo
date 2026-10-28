// @vitest-environment jsdom
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "./errors";
import { pollWhile } from "./query";

type Job = { status: "running" | "done" };

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

/**
 * Observes one query polled by `pollWhile(running, 2 s, idleMs)`: the first
 * request gets `first`, later ones `then`. Polling runs only in a browser.
 */
function poll(first: Job, then?: () => Promise<Job>, idleMs?: number | false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let requests = 0;
  const observer = new QueryObserver(client, {
    queryKey: ["job"],
    queryFn: () => (requests++ === 0 || !then ? Promise.resolve(first) : then()),
    refetchInterval: pollWhile<Job>((job) => job?.status === "running", 2_000, idleMs)
  });
  const unsubscribe = observer.subscribe(() => {});
  return {
    requests: () => requests,
    stop: () => {
      unsubscribe();
      client.clear();
    }
  };
}

const refuse = (status: number) => () => Promise.reject(new EneoApiError("no", { status }));

describe("pollWhile", () => {
  it.each([401, 403, 404, 410])("stops polling after a final %i", async (status) => {
    const query = poll({ status: "running" }, refuse(status));
    await vi.advanceTimersByTimeAsync(2_100);
    expect(query.requests()).toBe(2);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(query.requests()).toBe(2);
    query.stop();
  });

  it.each([409, 429, 500])(
    "keeps polling at the active cadence after a passing %i",
    async (status) => {
      const query = poll({ status: "running" }, refuse(status));
      await vi.advanceTimersByTimeAsync(2_100);
      expect(query.requests()).toBe(2);

      await vi.advanceTimersByTimeAsync(4_000);
      expect(query.requests()).toBe(4);
      query.stop();
    }
  );

  it("polls an inactive state at the idle cadence, and not at all without one", async () => {
    const idle = poll({ status: "done" }, undefined, 15_000);
    await vi.advanceTimersByTimeAsync(14_000);
    expect(idle.requests()).toBe(1);
    await vi.advanceTimersByTimeAsync(1_100);
    expect(idle.requests()).toBe(2);
    idle.stop();

    const stopped = poll({ status: "done" });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(stopped.requests()).toBe(1);
    stopped.stop();
  });
});
