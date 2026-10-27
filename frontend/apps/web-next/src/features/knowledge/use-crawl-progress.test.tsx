// @vitest-environment jsdom
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";
import { makeSpace, makeWebsite } from "@/features/spaces/testing/space-fixture";
import type { CrawlRun, Website } from "./knowledge";

const state = vi.hoisted(() => ({ space: null as unknown, spaceDelay: 0 }));
const api = vi.hoisted(() => ({ GET: vi.fn() }));
/** A value read now and delivered after `ms`, like a response over the network. */
const later = vi.hoisted(
  () =>
    <Value,>(ms: number, value: Value) =>
      new Promise<Value>((resolve) => setTimeout(() => resolve(value), ms))
);

// The space lives in its query as in the app: a refresh reads `state.space`
// again, after `state.spaceDelay`.
vi.mock("@/features/spaces/use-space", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useSpace: () => {
      const { data: space } = useQuery({
        queryKey: ["spaces", "space-1"],
        queryFn: () => later(state.spaceDelay, state.space as Space),
        initialData: () => state.space as Space
      });
      return { space, routeId: "space-1" };
    }
  };
});
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { useCrawlProgress } from "./use-crawl-progress";

const PROGRESS = "/api/v1/spaces/{id}/knowledge/websites/crawl-progress/";
const NETWORK_MS = 10;

function run(overrides: Partial<CrawlRun> = {}): CrawlRun {
  return {
    id: "run-1",
    phase: "running",
    outcome: null,
    status: "in progress",
    origin: "manual",
    pages_crawled: 10,
    files_downloaded: 0,
    pages_failed: 0,
    files_failed: 0,
    result_location: null,
    finished_at: null,
    failure_code: null,
    failure_detail: null,
    created_at: "2026-10-26T10:00:00Z",
    updated_at: "2026-10-26T10:01:00Z",
    ...overrides
  } as CrawlRun;
}

function ended(overrides: Partial<CrawlRun> = {}): CrawlRun {
  return run({
    phase: "terminal",
    outcome: "succeeded",
    status: "complete",
    finished_at: "2026-10-26T10:04:00Z",
    updated_at: "2026-10-26T10:04:00Z",
    ...overrides
  });
}

const website = (id: string, latest: CrawlRun | null) =>
  makeWebsite({ id, latest_crawl: latest }) as unknown as Website;

let progress: { website_id: string; latest_crawl: CrawlRun }[] = [];
let progressFails = false;

async function flush(ms = 20) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Until the next progress read has answered (the poll waits two seconds after each answer). */
const nextPoll = () => flush(2_000 + 2 * NETWORK_MS);

const progressPolls = () => api.GET.mock.calls.filter(([path]) => path === PROGRESS).length;

beforeEach(() => {
  vi.useFakeTimers();
  progress = [];
  progressFails = false;
  state.spaceDelay = 0;
  api.GET.mockImplementation((path: string) =>
    path === PROGRESS
      ? later(
          NETWORK_MS,
          progressFails
            ? { error: { message: "Not Found" }, response: new Response("{}", { status: 404 }) }
            : { data: { items: progress }, response: new Response("{}") }
        )
      : Promise.reject(new Error(`unexpected ${path}`))
  );
});

afterEach(() => {
  vi.useRealTimers();
  api.GET.mockReset();
});

/** The space now shows these websites; it says so when it is next read. */
function spaceShows(websites: Website[]) {
  state.space = makeSpace({ websites });
}

function renderProgress(websites: Website[]) {
  spaceShows(websites);
  const rendered = renderHookInApp(() => {
    const { space } = useSpace();
    return useCrawlProgress(space.knowledge.websites.items as unknown as Website[]);
  });
  const invalidate = vi.spyOn(rendered.queryClient, "invalidateQueries");
  const spaceRefreshes = () =>
    invalidate.mock.calls.filter(
      ([filters]) => JSON.stringify(filters?.queryKey) === JSON.stringify(["spaces", "space-1"])
    ).length;
  const shown = (id: string) =>
    rendered.result.current.websites.find((item) => item.id === id)?.latest_crawl;
  return { ...rendered, spaceRefreshes, shown };
}

describe("useCrawlProgress", () => {
  it("polls nothing while no crawl runs", async () => {
    const { result } = renderProgress([website("w1", null)]);
    const idle = result.current.websites;
    await flush(10_000);
    expect(progressPolls()).toBe(0);
    expect(result.current.websites).toBe(idle);
    expect(result.current.pollSpaceFast).toBe(false);
  });

  it("follows a running crawl through the poll, every two seconds, and leaves the space on its slow poll", async () => {
    progress = [
      {
        website_id: "w1",
        latest_crawl: run({ pages_crawled: 25, updated_at: "2026-10-26T10:02:00Z" })
      }
    ];
    const { result, shown } = renderProgress([website("w1", run())]);
    await flush();
    expect(shown("w1")?.pages_crawled).toBe(25);
    expect(result.current.pollSpaceFast).toBe(false);

    progress = [
      {
        website_id: "w1",
        latest_crawl: run({ pages_crawled: 60, updated_at: "2026-10-26T10:03:00Z" })
      }
    ];
    const before = progressPolls();
    await nextPoll();
    expect(progressPolls()).toBe(before + 1);
    expect(shown("w1")?.pages_crawled).toBe(60);
  });

  it("shows a crawl that starts from the poll, and refreshes the space once when one ends", async () => {
    progress = [{ website_id: "w1", latest_crawl: run() }];
    const { spaceRefreshes, shown } = renderProgress([website("w1", run()), website("w2", null)]);
    await flush();

    progress = [
      { website_id: "w1", latest_crawl: run() },
      { website_id: "w2", latest_crawl: run({ id: "run-2" }) }
    ];
    await nextPoll();
    expect(shown("w2")?.id).toBe("run-2");
    expect(spaceRefreshes()).toBe(0);

    progress = [{ website_id: "w2", latest_crawl: run({ id: "run-2" }) }];
    spaceShows([website("w1", ended()), website("w2", run({ id: "run-2" }))]);
    await nextPoll();
    expect(spaceRefreshes()).toBe(1);
    expect(shown("w1")?.phase).toBe("terminal");

    // Progress within a crawl refreshes nothing.
    progress = [{ website_id: "w2", latest_crawl: run({ id: "run-2", pages_crawled: 80 }) }];
    await nextPoll();
    expect(shown("w2")?.pages_crawled).toBe(80);
    expect(spaceRefreshes()).toBe(1);
  });

  it("keeps following a newer crawl that the space read before it started", async () => {
    progress = [{ website_id: "w1", latest_crawl: run() }];
    const { spaceRefreshes, shown } = renderProgress([website("w1", run())]);
    await flush();

    // The crawl ends and the next one starts; the space's refresh was read
    // between the two, so it shows the first as ended and knows nothing of
    // the second.
    const next = { id: "run-2", created_at: "2026-10-26T10:05:00Z" };
    progress = [
      { website_id: "w1", latest_crawl: run({ ...next, updated_at: "2026-10-26T10:05:30Z" }) }
    ];
    spaceShows([website("w1", ended())]);
    await nextPoll();
    expect(spaceRefreshes()).toBe(1);
    expect(shown("w1")?.id).toBe("run-2");

    progress = [
      {
        website_id: "w1",
        latest_crawl: run({ ...next, pages_crawled: 50, updated_at: "2026-10-26T10:06:00Z" })
      }
    ];
    const polls = progressPolls();
    await nextPoll();
    expect(progressPolls()).toBe(polls + 1);
    expect(shown("w1")?.pages_crawled).toBe(50);

    // When it ends, the space is refreshed and the polling stops.
    progress = [];
    spaceShows([website("w1", ended({ ...next, updated_at: "2026-10-26T10:09:00Z" }))]);
    await nextPoll();
    expect(spaceRefreshes()).toBe(2);
    expect(shown("w1")).toMatchObject({ id: "run-2", phase: "terminal" });
    const done = progressPolls();
    await flush(10_000);
    expect(progressPolls()).toBe(done);
  });

  it("keeps a crawl's last progress until the space says how it ended", async () => {
    state.spaceDelay = 500;
    const queued = run({
      phase: "queued",
      status: "queued",
      pages_crawled: 0,
      updated_at: "2026-10-26T10:00:00Z"
    });
    progress = [{ website_id: "w1", latest_crawl: run({ pages_crawled: 80 }) }];
    const { spaceRefreshes, shown } = renderProgress([website("w1", queued)]);
    await flush();
    expect(shown("w1")).toMatchObject({ phase: "running", pages_crawled: 80 });

    progress = [];
    spaceShows([website("w1", ended({ pages_crawled: 120 }))]);
    await nextPoll();
    expect(spaceRefreshes()).toBe(1);
    // The space's answer is on its way: the crawl does not step back to queued.
    expect(shown("w1")).toMatchObject({ phase: "running", pages_crawled: 80 });

    await flush(600);
    expect(shown("w1")).toMatchObject({ phase: "terminal", pages_crawled: 120 });
  });

  it("refreshes the space once per read when it shows a crawl a later progress read no longer has", async () => {
    // The crawl ended between the space's read and the first progress read.
    state.spaceDelay = 3_000;
    const { spaceRefreshes } = renderProgress([website("w1", run())]);
    await flush();
    expect(spaceRefreshes()).toBe(1);
    // While the space answers, further reads of the same state refresh nothing more.
    await flush(2_500);
    expect(spaceRefreshes()).toBe(1);
    // A space read that still shows it (it crossed the end) is refreshed again.
    await nextPoll();
    expect(spaceRefreshes()).toBe(2);
  });

  it("does not take a progress read from before the space's read as an ended crawl", async () => {
    progress = [{ website_id: "w1", latest_crawl: run() }];
    const rendered = renderProgress([website("w1", run())]);
    const { spaceRefreshes, shown } = rendered;
    await flush();
    progress = [];
    spaceShows([website("w1", ended())]);
    await nextPoll();
    expect(spaceRefreshes()).toBe(1);
    expect(shown("w1")?.phase).toBe("terminal");

    // A new crawl starts; its start refreshes the space. The cached progress,
    // read before it, does not have it, and says nothing about it.
    const next = {
      id: "run-2",
      created_at: "2026-10-26T10:10:00Z",
      updated_at: "2026-10-26T10:10:00Z"
    };
    spaceShows([website("w1", run({ ...next, phase: "queued", status: "queued" }))]);
    void rendered.queryClient.refetchQueries({ queryKey: ["spaces", "space-1"] });
    await flush();
    expect(shown("w1")?.id).toBe("run-2");
    expect(spaceRefreshes()).toBe(1);

    // It ends before the next progress read, which reads the same as the
    // cached one but after the space: the space is refreshed.
    spaceShows([website("w1", ended({ ...next, updated_at: "2026-10-26T10:11:00Z" }))]);
    await nextPoll();
    expect(spaceRefreshes()).toBe(2);
    expect(shown("w1")).toMatchObject({ id: "run-2", phase: "terminal" });
  });

  it("falls back to polling the space quickly when the crawl progress cannot be read", async () => {
    progressFails = true;
    const { result } = renderProgress([website("w1", run())]);
    const fromSpace = result.current.websites;
    await flush(100);
    expect(result.current.pollSpaceFast).toBe(true);
    expect(result.current.websites).toBe(fromSpace);
    // The failing read is retried on the slow cadence, not every two seconds.
    const before = progressPolls();
    await flush(10_000);
    expect(progressPolls()).toBe(before);
  });
});
