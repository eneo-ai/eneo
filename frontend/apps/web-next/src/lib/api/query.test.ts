// @vitest-environment jsdom
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "./errors";
import { makeQueryClient, pollWhile, readCached, readFresh, warmQuery } from "./query";

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

  it("keeps polling at the active cadence after a network error", async () => {
    const query = poll({ status: "running" }, () =>
      Promise.reject(new TypeError("Failed to fetch"))
    );
    await vi.advanceTimersByTimeAsync(6_100);
    expect(query.requests()).toBe(4);
    query.stop();
  });

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

/** A backend resource that answers with `answers`, one per request, repeating the last. */
function resource(...answers: Array<string | number>) {
  let requests = 0;
  return {
    requests: () => requests,
    options: {
      queryKey: ["resource"],
      queryFn: async () => {
        const answer = answers[Math.min(requests++, answers.length - 1)];
        if (typeof answer === "number") throw new EneoApiError("no", { status: answer });
        return answer;
      }
    }
  };
}

/** Runs the retries' timers (backoff 1 + 2 + 4 s), not the cache's garbage collection. */
const retriesRun = () => vi.advanceTimersByTimeAsync(10_000);

async function settle<T>(promise: Promise<T>): Promise<PromiseSettledResult<T>> {
  const result = Promise.allSettled([promise]);
  await retriesRun();
  return (await result)[0]!;
}

describe("the default retry policy", () => {
  it.each([400, 403, 404, 409, 429])("fails at once on a %i", async (status) => {
    const backend = resource(status);
    const client = makeQueryClient();

    const observer = new QueryObserver(client, backend.options);
    const unsubscribe = observer.subscribe(() => {});
    await retriesRun();

    expect(observer.getCurrentResult().error).toMatchObject({ status });
    expect(backend.requests()).toBe(1);
    unsubscribe();
  });

  it("tries a server failure three more times", async () => {
    const backend = resource(503);
    const client = makeQueryClient();

    const observer = new QueryObserver(client, backend.options);
    const unsubscribe = observer.subscribe(() => {});
    await retriesRun();

    expect(observer.getCurrentResult().error).toMatchObject({ status: 503 });
    expect(backend.requests()).toBe(4);
    unsubscribe();
  });

  it("leaves a query's own policy alone", async () => {
    const backend = resource(503);
    const client = makeQueryClient();

    const observer = new QueryObserver(client, { ...backend.options, retry: false });
    const unsubscribe = observer.subscribe(() => {});
    await retriesRun();

    expect(backend.requests()).toBe(1);
    unsubscribe();
  });
});

describe("readCached", () => {
  it("returns cached data without asking, also after a failed background refresh", async () => {
    const backend = resource("first", 503);
    const client = makeQueryClient();
    await settle(readCached(client, backend.options));
    await settle(client.refetchQueries({ queryKey: ["resource"] }));
    expect(client.getQueryState(["resource"])?.isInvalidated).toBe(true);
    const asked = backend.requests();

    await expect(readCached(client, backend.options)).resolves.toBe("first");
    expect(backend.requests()).toBe(asked);
  });

  it("loads what is not cached, and fails when it cannot", async () => {
    const backend = resource(404);

    const result = await settle(readCached(makeQueryClient(), backend.options));

    expect(result).toMatchObject({ status: "rejected", reason: { status: 404 } });
  });
});

describe("readFresh", () => {
  it("asks again after a failed background refresh, and keeps the guard's 404", async () => {
    const backend = resource("first", 403, 404);
    const client = makeQueryClient();
    await settle(readCached(client, backend.options));
    await settle(client.refetchQueries({ queryKey: ["resource"] }));
    const asked = backend.requests();

    const result = await settle(readFresh(client, backend.options));

    expect(result).toMatchObject({ status: "rejected", reason: { status: 404 } });
    expect(backend.requests()).toBe(asked + 1);
  });

  it("fails a cold read at once, without retries", async () => {
    const backend = resource(503);

    const result = await settle(readFresh(makeQueryClient(), backend.options));

    expect(result).toMatchObject({ status: "rejected", reason: { status: 503 } });
    expect(backend.requests()).toBe(1);
  });
});

describe("warmQuery", () => {
  it("keeps the query's retries for a component that joins it", async () => {
    const backend = resource(503, "loaded");
    const client = makeQueryClient();

    warmQuery(client, backend.options);
    const observer = new QueryObserver(client, backend.options);
    const unsubscribe = observer.subscribe(() => {});
    await retriesRun();

    expect(observer.getCurrentResult().data).toBe("loaded");
    expect(backend.requests()).toBe(2);
    unsubscribe();
  });

  it("keeps a query's deliberate retry: false", async () => {
    const backend = resource(503, "loaded");
    const client = makeQueryClient();
    const options = { ...backend.options, retry: false as const };

    warmQuery(client, options);
    const observer = new QueryObserver(client, options);
    const unsubscribe = observer.subscribe(() => {});
    await retriesRun();

    expect(observer.getCurrentResult().error).toMatchObject({ status: 503 });
    expect(backend.requests()).toBe(1);
    unsubscribe();
  });
});
