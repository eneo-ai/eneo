// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { makeSpace, makeWebsite } from "@/features/spaces/testing/space-fixture";

type Run = Record<string, unknown>;

const run = (overrides: Run = {}): Run => ({
  id: "crawl-2",
  status: "complete",
  phase: "terminal",
  outcome: "succeeded",
  origin: "manual",
  pages_crawled: 12,
  pages_unchanged: 0,
  files_downloaded: 0,
  files_unchanged: 0,
  pages_failed: 0,
  files_failed: 0,
  failure_summary: null,
  failure_code: null,
  failure_detail: null,
  result_location: null,
  created_at: "2026-09-25T08:00:00Z",
  finished_at: "2026-09-25T08:10:00Z",
  cancel_requested_at: null,
  attempt_count: 1,
  ...overrides
});

const state = vi.hoisted(() => ({
  latest: null as Run | null,
  history: [] as Run[],
  olderHistory: [] as Run[],
  historyTotal: 0,
  historyError: false,
  latestError: false,
  blobTitle: "lou.html",
  requests: [] as string[]
}));
const post = vi.hoisted(() => vi.fn());

// The rest of next/navigation is real: @/lib/navigation reads its hooks on import.
vi.mock("@/lib/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/navigation")>()),
  useRouter: () => ({ push: () => {}, prefetch: () => {} }),
  useSearchParams: () => new URLSearchParams()
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => makeSpace() as Space) };
});
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string, options?: { params?: { query?: { cursor?: string | null } } }) => {
      const cursor = options?.params?.query?.cursor ?? null;
      state.requests.push(`${path}${cursor ? `?cursor=${cursor}` : ""}`);
      if (
        (path === "/api/v1/websites/{id}/runs/" && cursor && state.historyError) ||
        (path === "/api/v1/websites/{id}/runs/latest/" && state.latestError)
      )
        return Promise.resolve({
          error: { detail: "unavailable" },
          response: new Response(null, { status: state.latestError ? 404 : 503 })
        });
      const data =
        path === "/api/v1/websites/{id}/"
          ? makeWebsite()
          : path === "/api/v1/websites/{id}/runs/latest/"
            ? state.latest
            : path === "/api/v1/websites/{id}/runs/"
              ? cursor
                ? { items: state.olderHistory, total_count: state.historyTotal, next_cursor: null }
                : {
                    items: state.history,
                    total_count: state.historyTotal,
                    next_cursor: state.olderHistory.length > 0 ? "older" : null
                  }
              : path === "/api/v1/websites/{id}/info-blobs/page/"
                ? {
                    items: [{ id: "blob-1", metadata: { title: state.blobTitle, size: 2048 } }],
                    total_count: 1,
                    next_cursor: null
                  }
                : { items: [], total_count: 0, next_cursor: null, details_available: true };
      return Promise.resolve({ data, response: new Response("{}") });
    },
    POST: post
  }
}));

import { WebsiteDetail } from "@/features/knowledge/detail/website-detail.client";

function setRuns(latest: Run | null, older: Run[] = []) {
  state.latest = latest;
  state.history = latest ? [latest] : [];
  state.olderHistory = older;
  state.historyTotal = state.history.length + older.length;
}

afterEach(() => {
  cleanup();
  setRuns(run());
  state.blobTitle = "lou.html";
  state.historyError = false;
  state.latestError = false;
  vi.useRealTimers();
  state.requests = [];
  post.mockReset();
});

// afterEach has not run before the first test.
setRuns(run());

describe("WebsiteDetail", () => {
  it("switches between crawls and indexed content with Astryx tabs", async () => {
    // makeSpace() owns website-1, so the page offers its crawl controls.
    expect(makeSpace().id).toBe(makeWebsite().space_id);
    const { container } = renderInApp(<WebsiteDetail websiteId="website-1" />);

    const tablist = await screen.findByRole("tablist", { name: "Indexeringar och innehåll" });
    const crawls = within(tablist).getByRole("tab", { name: "Indexeringar" });
    expect(crawls.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel", { name: "Indexeringar" })).toBeTruthy();
    // Each tab's table takes the tab's name.
    expect(screen.getByRole("table", { name: "Indexeringar" })).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(within(tablist).getByRole("tab", { name: "Indexerat innehåll" }));
    expect(screen.getByRole("tabpanel", { name: "Indexerat innehåll" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Indexerat innehåll" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("offers Kör igen with a history and Synkronisera nu before the first run", async () => {
    renderInApp(<WebsiteDetail websiteId="website-1" />);
    expect(await screen.findByRole("button", { name: "Kör igen" })).toBeTruthy();
    cleanup();

    setRuns(null);
    renderInApp(<WebsiteDetail websiteId="website-1" />);
    expect(await screen.findByRole("button", { name: "Synkronisera nu" })).toBeTruthy();
  });

  it("stops a running crawl after a confirmation", async () => {
    setRuns(run({ phase: "running", outcome: null, status: "in progress", finished_at: null }));
    post.mockImplementation(() => {
      setRuns(run({ phase: "stopping", outcome: null, status: "in progress", finished_at: null }));
      return Promise.resolve({ data: state.latest, response: new Response("{}") });
    });
    renderInApp(<WebsiteDetail websiteId="website-1" />);

    fireEvent.click(await screen.findByRole("button", { name: "Stoppa" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Stoppa synkroniseringen?" });
    expect(dialog.textContent).toContain("upphandlingsmyndigheten.se");
    fireEvent.click(within(dialog).getByRole("button", { name: "Stoppa" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/crawl-runs/{id}/cancel/", {
        params: { path: { id: "crawl-2" } }
      })
    );
    // Once the stop is requested the button says so and cannot be pressed again.
    const stopping = await screen.findByRole("button", { name: "Stoppar..." });
    expect(
      stopping.hasAttribute("disabled") || stopping.getAttribute("aria-disabled")
    ).toBeTruthy();
  });

  it("shows the run as stoppable once a crawl is started", async () => {
    post.mockImplementation(() => {
      setRuns(run({ id: "crawl-3", phase: "queued", outcome: null, status: "queued" }));
      return Promise.resolve({ data: state.latest, response: new Response("{}") });
    });
    renderInApp(<WebsiteDetail websiteId="website-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Kör igen" }));
    fireEvent.click(
      within(await screen.findByRole("alertdialog", { name: "Synkronisera webbplats" })).getByRole(
        "button",
        { name: "Starta synkronisering" }
      )
    );

    expect(await screen.findByRole("button", { name: "Stoppa" })).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/api/v1/websites/{id}/run/", {
      params: { path: { id: "website-1" } }
    });
  });

  it("keeps focus on a busy Starta synkronisering and starts one crawl", async () => {
    post.mockReturnValue(new Promise(() => {}));
    renderInApp(<WebsiteDetail websiteId="website-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Kör igen" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Synkronisera webbplats" });
    const start = within(dialog).getByRole("button", { name: "Starta synkronisering" });
    start.focus();

    fireEvent.click(start);

    const busy = await within(dialog).findByRole("button", { name: "Startar..." });
    expect(busy).toBe(start);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(busy);
    fireEvent.click(busy);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("updates indexed content and offers Kör igen when the active crawl finishes", async () => {
    setRuns(run({ phase: "running", outcome: null, status: "in progress", finished_at: null }));
    const { queryClient } = renderInApp(<WebsiteDetail websiteId="website-1" />);
    await screen.findByRole("button", { name: "Stoppa" });

    setRuns(run());
    state.blobTitle = "updated.html";
    await queryClient.invalidateQueries({
      queryKey: ["websites", "website-1", "crawl-runs", "latest"]
    });

    expect(await screen.findByRole("button", { name: "Kör igen" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Indexerat innehåll" }));
    expect(await screen.findByText("updated.html")).toBeTruthy();
  });

  it("loads older crawls a page at a time", async () => {
    setRuns(run(), [
      run({
        id: "crawl-1",
        created_at: "2026-09-20T08:00:00Z",
        finished_at: "2026-09-20T08:10:00Z"
      }),
      run({
        id: "crawl-0",
        created_at: "2026-09-15T08:00:00Z",
        finished_at: "2026-09-15T08:10:00Z"
      })
    ]);
    renderInApp(<WebsiteDetail websiteId="website-1" />);

    const table = await screen.findByRole("table", { name: "Indexeringar" });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Visa äldre genomsökningar (1/3)" }));

    await waitFor(() =>
      expect(
        within(screen.getByRole("table", { name: "Indexeringar" })).getAllByRole("row")
      ).toHaveLength(4)
    );
    expect(state.requests).toContain("/api/v1/websites/{id}/runs/?cursor=older");
    expect(screen.queryByRole("button", { name: /Visa äldre genomsökningar/ })).toBeNull();
  });

  it("keeps loaded crawl rows and retries a failed next page in place", async () => {
    setRuns(run(), [run({ id: "older", created_at: "2026-09-20T08:00:00Z" })]);
    state.historyError = true;
    renderInApp(<WebsiteDetail websiteId="website-1" />);
    const table = await screen.findByRole("table", { name: "Indexeringar" });
    fireEvent.click(screen.getByRole("button", { name: "Visa äldre genomsökningar (1/2)" }));
    const retry = await screen.findByRole("button", { name: /^Försök igen/ });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    state.historyError = false;
    fireEvent.click(retry);
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(3));
    expect(screen.queryByRole("button", { name: /^Försök igen/ })).toBeNull();
    expect(
      state.requests.filter((path) => path === "/api/v1/websites/{id}/runs/?cursor=older")
    ).toHaveLength(2);
  });

  it("stops polling after the latest crawl becomes unavailable", async () => {
    setRuns(run({ phase: "running", outcome: null, status: "in progress", finished_at: null }));
    const { queryClient } = renderInApp(<WebsiteDetail websiteId="website-1" />);
    await screen.findByRole("button", { name: "Stoppa" });
    vi.useFakeTimers();
    state.latestError = true;
    await act(() =>
      queryClient.invalidateQueries({
        queryKey: ["websites", "website-1", "crawl-runs", "latest"],
        exact: true
      })
    );
    const count = state.requests.filter(
      (path) => path === "/api/v1/websites/{id}/runs/latest/"
    ).length;
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(
      state.requests.filter((path) => path === "/api/v1/websites/{id}/runs/latest/")
    ).toHaveLength(count);
  });

  it("says above the content when the latest finished run had failures", async () => {
    setRuns(run({ outcome: "partial", pages_failed: 2, failure_summary: { http_404: 2 } }));
    renderInApp(<WebsiteDetail websiteId="website-1" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Indexerat innehåll" }));

    expect(screen.getByText("Senaste avslutade körningen hade fel")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Visa sidor som inte kunde indexeras (2)" })
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: "Sidor" }).getAttribute("aria-checked")).toBe(
      "true"
    );
    // Nothing was recorded for the run: the dialog says so instead of a list.
    expect(
      await within(dialog).findByText(
        "Inga misslyckade adresser av den här typen har registrerats."
      )
    ).toBeTruthy();
    // The dialog can hand over to a new run of the whole website.
    fireEvent.click(within(dialog).getByRole("button", { name: "Kör om hela webbplatsen" }));
    expect(await screen.findByRole("alertdialog", { name: "Synkronisera webbplats" })).toBeTruthy();
  });
});
