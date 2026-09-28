// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { renderInApp } from "@/test/render";
import { JobIndicator } from "./job-indicator";
import { type Job, JobsProvider, useJobs } from "./use-jobs";

const job = { id: "job-1", name: "Avtal.pdf", status: "in progress" } as Job;
const api = vi.hoisted(() => ({ items: [] as Job[] }));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async () => ({ data: { items: api.items }, response: new Response("{}") }))
  }
}));

beforeEach(() => {
  api.items = [job];
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

it("keeps its context still when the jobs arrive", async () => {
  // The provider sits above every page: a context that changes while React
  // still hydrates a page makes React render the page again from scratch.
  const seen: ReturnType<typeof useJobs>[] = [];
  function Consumer() {
    seen.push(useJobs());
    return null;
  }

  const { queryClient } = renderInApp(
    <JobsProvider>
      <Consumer />
    </JobsProvider>
  );

  await waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([job]));
  expect(new Set(seen).size).toBe(1);
});

it("shows a crawl that appears after the first empty jobs response", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  api.items = [];

  const { queryClient } = renderInApp(
    <JobsProvider>
      <JobIndicator />
    </JobsProvider>
  );
  await waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([]));
  expect(screen.getByRole("button", { name: "Aviseringar" })).toBeTruthy();

  api.items = [{ ...job, task: "crawl", name: "Devize" }];
  await act(() => vi.advanceTimersByTimeAsync(30_000));

  const bell = await screen.findByRole("button", { name: "Aviseringar, 1 pågår" });
  fireEvent.click(bell);
  const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });
  expect(within(panel).getByText("Devize")).toBeTruthy();
});

it("checks quickly after a new job is tracked even if the first fetch is still empty", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  api.items = [];
  function StartJob() {
    const { trackJob } = useJobs();
    return (
      <button type="button" onClick={trackJob}>
        Start job
      </button>
    );
  }

  const { queryClient } = renderInApp(
    <JobsProvider>
      <JobIndicator />
      <StartJob />
    </JobsProvider>
  );
  await waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([]));
  fireEvent.click(screen.getByRole("button", { name: "Start job" }));
  await waitFor(() => expect(browserApi.GET).toHaveBeenCalledTimes(2));

  api.items = [{ ...job, task: "crawl", name: "Devize" }];
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  expect(browserApi.GET).toHaveBeenCalledTimes(3);
  expect(await screen.findByRole("button", { name: "Aviseringar, 1 pågår" })).toBeTruthy();
});

it("checks active jobs every two seconds until they finish", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  api.items = [{ ...job, task: "crawl", name: "Devize" }];
  renderInApp(
    <JobsProvider>
      <JobIndicator />
    </JobsProvider>
  );
  await screen.findByRole("button", { name: "Aviseringar, 1 pågår" });

  api.items = [{ ...job, task: "crawl", name: "Devize", status: "complete" }];
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  const bell = await screen.findByRole("button", { name: "Aviseringar" });
  fireEvent.click(bell);
  const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });
  expect(within(panel).getByText("Klar")).toBeTruthy();
});
