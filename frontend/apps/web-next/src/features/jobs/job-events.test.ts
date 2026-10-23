// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { FakeEventSource, installFakeEventSource } from "./job-events.test-support";

type Module = typeof import("./job-events");
let events: Module;

let fake: ReturnType<typeof installFakeEventSource>;

beforeEach(async () => {
  fake = installFakeEventSource();
  // The module keeps the shared connection in module state: start it fresh.
  vi.resetModules();
  events = await import("./job-events");
});

afterEach(() => {
  fake.restore();
  vi.useRealTimers();
});

const latest = () => fake.latest();

it("opens one feed for every subscriber and closes it with the last one", () => {
  const stopA = events.subscribeJobEvents(() => {});
  const stopB = events.subscribeJobEvents(() => {});
  expect(FakeEventSource.instances).toHaveLength(1);
  expect(latest().url).toBe("/api/jobs/events");

  stopA();
  expect(latest().closed).toBe(false);
  stopB();
  expect(latest().closed).toBe(true);
});

it("hands every subscriber the parsed job and ignores malformed events", () => {
  const seen: unknown[] = [];
  events.subscribeJobEvents((job) => seen.push(job));
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

  events.subscribeJobEvents(() => {}, reconnects);
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
  events.subscribeJobEvents(() => {});
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
  const stop = events.subscribeJobEvents(() => {});
  latest().refuse();
  stop();
  vi.advanceTimersByTime(60_000);
  expect(FakeEventSource.instances).toHaveLength(1);
});
