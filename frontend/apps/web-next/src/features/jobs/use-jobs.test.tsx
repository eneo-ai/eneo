// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { renderInApp } from "@/test/render";
import { JobIndicator } from "./job-indicator";
import { type Job, JobsProvider, useJobs } from "./use-jobs";

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/toast", () => ({ toast }));

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
      <button type="button" onClick={() => trackJob()}>
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

it("refreshes knowledge when a crawl fails, as its partial results have landed", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  api.items = [{ ...job, task: "crawl", name: "Devize" }];
  const { queryClient } = renderInApp(
    <JobsProvider>
      <JobIndicator />
    </JobsProvider>
  );
  await screen.findByRole("button", { name: "Aviseringar, 1 pågår" });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  api.items = [
    {
      ...job,
      task: "crawl",
      name: "Devize",
      status: "failed",
      failure_code: "tenant_quota_exceeded"
    }
  ];
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  await screen.findByRole("button", { name: "Aviseringar" });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["websites"] });
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

it("catches an upload whose job is already finished on the first poll", async () => {
  // The upload call returned the job; the worker processed the file before
  // the first poll. The seed in trackJob(job) makes that poll a completion:
  // the collection refreshes and the user hears the file is searchable.
  const uploaded = {
    ...job,
    task: "upload_info_blob",
    status: "complete",
    result_location: "/api/v1/info-blobs/5d1b9c1e-0b4e-4c21-9d7c-2f0f0a6d3e11/"
  } as Job;
  api.items = [uploaded];
  function Track() {
    const { trackJob } = useJobs();
    return (
      <button type="button" onClick={() => trackJob({ ...uploaded, status: "queued" })}>
        Track
      </button>
    );
  }

  const { queryClient } = renderInApp(
    <JobsProvider>
      <Track />
    </JobsProvider>
  );
  await waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([uploaded]));
  // Seen finished from the start: no transition, no toast.
  expect(toast.success).not.toHaveBeenCalled();

  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  fireEvent.click(screen.getByRole("button", { name: "Track" }));
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Avtal.pdf är klar och sökbar."));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["collections"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["users", "me"] });
});

it("toasts a failed job with its reason", async () => {
  api.items = [{ ...job, task: "upload_info_blob", status: "in progress" } as Job];
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  const { queryClient } = renderInApp(
    <JobsProvider>
      <JobIndicator />
    </JobsProvider>
  );
  await waitFor(() => expect(queryClient.getQueryData(["jobs"])).toHaveLength(1));

  api.items = [
    { ...job, task: "upload_info_blob", status: "failed", failure_code: "encrypted" } as Job
  ];
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(
      "Avtal.pdf misslyckades.",
      expect.objectContaining({ description: expect.any(String) })
    )
  );
});
