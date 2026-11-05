// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JOB_EVENTS_PATH } from "@/lib/api/base";
import { FakeEventSource, installFakeEventSource } from "./job-events.test-support";

vi.mock("@/lib/api/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/base")>()),
  createApiEventSource: (url: string) => new EventSource(url)
}));

type Module = typeof import("./job-events");
let events: Module;

let fake: ReturnType<typeof installFakeEventSource>;

beforeEach(async () => {
  fake = installFakeEventSource();
  // The module keeps the shared connection in module state: start it fresh.
  vi.resetModules();
  events = await import("./job-events");
});

// A subscriber left behind would keep its module's tab listener on document.
const stops: (() => void)[] = [];
const subscribe: Module["subscribeJobEvents"] = (...args) => {
  const stop = events.subscribeJobEvents(...args);
  stops.push(stop);
  return stop;
};

afterEach(() => {
  stops.splice(0).forEach((stop) => stop());
  fake.restore();
  vi.useRealTimers();
});

const latest = () => fake.latest();

it("opens one feed for every subscriber and closes it with the last one", () => {
  const stopA = subscribe(() => {});
  const stopB = subscribe(() => {});
  expect(FakeEventSource.instances).toHaveLength(1);
  expect(latest().url).toBe(JOB_EVENTS_PATH);

  stopA();
  expect(latest().closed).toBe(false);
  stopB();
  expect(latest().closed).toBe(true);
});

it("hands every subscriber the parsed job and ignores malformed events", () => {
  const seen: unknown[] = [];
  subscribe((job) => seen.push(job));
  latest().open();
  latest().job({ id: "job-1", status: "complete" });
  latest().dispatchEvent(new MessageEvent("job", { data: "not json" }));
  latest().job({ status: "complete" });
  expect(seen).toEqual([{ id: "job-1", status: "complete" }]);
});

it("reports the connection and announces a reconnect, not the first open", () => {
  const reconnects = vi.fn();
  const { result } = renderHook(() => events.useJobEventsConnected());
  expect(result.current).toBe(false);

  subscribe(() => {}, reconnects);
  act(() => latest().open());
  expect(result.current).toBe(true);
  expect(reconnects).not.toHaveBeenCalled();

  act(() => latest().blip());
  expect(result.current).toBe(false);
  expect(latest().closed).toBe(false);

  act(() => latest().open());
  expect(result.current).toBe(true);
  expect(reconnects).toHaveBeenCalledTimes(1);
});

it("waits before reopening a feed the server refused", () => {
  vi.useFakeTimers();
  subscribe(() => {});
  latest().open();
  latest().refuse();
  expect(latest().closed).toBe(true);
  expect(FakeEventSource.instances).toHaveLength(1);

  vi.advanceTimersByTime(29_000);
  expect(FakeEventSource.instances).toHaveLength(1);
  vi.advanceTimersByTime(1_000);
  expect(FakeEventSource.instances).toHaveLength(2);
});

it("does not reopen after the last subscriber left", () => {
  vi.useFakeTimers();
  const stop = subscribe(() => {});
  latest().refuse();
  stop();
  vi.advanceTimersByTime(60_000);
  expect(FakeEventSource.instances).toHaveLength(1);
});

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("in a hidden tab", () => {
  afterEach(() => {
    Reflect.deleteProperty(document, "visibilityState");
  });

  it("closes the feed after the grace period and reopens it, with a refetch, when shown", () => {
    vi.useFakeTimers();
    const reconnects = vi.fn();
    subscribe(() => {}, reconnects);
    latest().open();

    setVisibility("hidden");
    vi.advanceTimersByTime(89_000);
    expect(latest().closed).toBe(false);
    vi.advanceTimersByTime(1_000);
    expect(latest().closed).toBe(true);

    setVisibility("visible");
    expect(FakeEventSource.instances).toHaveLength(2);
    latest().open();
    expect(reconnects).toHaveBeenCalledTimes(1);
  });

  it("keeps the feed through a short hide", () => {
    vi.useFakeTimers();
    subscribe(() => {});
    latest().open();
    setVisibility("hidden");
    vi.advanceTimersByTime(60_000);
    setVisibility("visible");
    vi.advanceTimersByTime(60_000);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(latest().closed).toBe(false);
  });

  it("does not retry a refused feed while closed for a hidden tab", () => {
    vi.useFakeTimers();
    subscribe(() => {});
    latest().refuse();
    setVisibility("hidden");
    vi.advanceTimersByTime(30_000);
    expect(FakeEventSource.instances).toHaveLength(2);
    vi.advanceTimersByTime(600_000);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(latest().closed).toBe(true);
  });

  it("keeps a refused feed's wait across the hidden tab's close", () => {
    vi.useFakeTimers();
    subscribe(() => {});
    latest().open();
    setVisibility("hidden");
    vi.advanceTimersByTime(89_000);
    latest().refuse();
    // Closed for the hidden tab a second later, shown a second after that.
    vi.advanceTimersByTime(2_000);
    setVisibility("visible");
    expect(FakeEventSource.instances).toHaveLength(1);
    vi.advanceTimersByTime(27_000);
    expect(FakeEventSource.instances).toHaveLength(1);
    vi.advanceTimersByTime(1_000);
    expect(FakeEventSource.instances).toHaveLength(2);
  });

  it("keeps a refused feed's wait when the tab is shown again", () => {
    vi.useFakeTimers();
    subscribe(() => {});
    latest().refuse();
    setVisibility("hidden");
    setVisibility("visible");
    expect(FakeEventSource.instances).toHaveLength(1);
    vi.advanceTimersByTime(30_000);
    expect(FakeEventSource.instances).toHaveLength(2);
  });

  it("stops watching the tab once the last subscriber leaves", () => {
    vi.useFakeTimers();
    const stop = subscribe(() => {});
    stop();
    setVisibility("hidden");
    setVisibility("visible");
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
