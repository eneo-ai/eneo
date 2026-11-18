// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import {
  PENDING_IMPORTS_STORAGE_KEY,
  pendingImports,
  resetPendingImports,
  trackImports
} from "@/features/knowledge/integrations/import-completion";
import {
  pendingSyncs,
  resetPendingSyncs,
  trackSyncs
} from "@/features/knowledge/integrations/pending-syncs";
import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import { router } from "@/test/navigation";
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
const announce = vi.hoisted(() => vi.fn());
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => announce
}));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

// Transport authentication has separate coverage in upload-session.test.tsx.
vi.mock("@/lib/api/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/base")>()),
  createApiEventSource: (url: string) => new EventSource(url),
  onBrowserApiRequest: async ({ request }: { request: Request }) => request,
  onRawRefusal: async () => {}
}));

const job = { id: "job-1", name: "Avtal.pdf", status: "in progress" } as Job;
const api = vi.hoisted(() => ({
  items: [] as Job[],
  space: null as unknown,
  spaceError: null as Error | null,
  /** While set, the jobs list waits for it. */
  jobsGate: null as Promise<void> | null,
  /** What a read by id answers: the job, or 404 for one that is gone. */
  byId: {} as Record<string, Job | 404>,
  /** A read by id of a job listed here waits for its promise. */
  byIdGates: {} as Record<string, Promise<void>>,
  /** While set, answers every read by id in place of `byId`; a rejection fails it. */
  answerById: null as ((id: string) => Promise<Job | 404>) | null
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string, init?: { params: { path: { id: string } } }) => {
      if (path === "/api/v1/spaces/{id}/" && api.spaceError) throw api.spaceError;
      if (path === "/api/v1/jobs/" && api.jobsGate) await api.jobsGate;
      if (path === "/api/v1/jobs/{id}/") {
        const id = init!.params.path.id;
        await api.byIdGates[id];
        const found = api.answerById ? await api.answerById(id) : api.byId[id];
        return found === 404 || found === undefined
          ? { error: { message: "Not found" }, response: new Response("{}", { status: 404 }) }
          : { data: found, response: new Response("{}") };
      }
      return {
        data: path === "/api/v1/spaces/{id}/" ? api.space : { items: api.items },
        response: new Response("{}")
      };
    })
  }
}));

/** The GET calls made so far to one API path. */
const callsTo = (path: string) =>
  (vi.mocked(browserApi.GET).mock.calls as unknown[][]).filter(([called]) => called === path);

beforeEach(() => {
  api.items = [job];
  api.spaceError = null;
  api.jobsGate = null;
  api.byId = {};
  api.byIdGates = {};
  api.answerById = null;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
  sessionStorage.clear();
  resetPendingImports();
  resetPendingSyncs();
});

it("reports a pushed job update without waiting for a poll", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  const fake = (await import("./job-events.test-support")).installFakeEventSource();
  api.items = [{ ...job, task: "upload_info_blob" }];
  renderInApp(
    <JobsProvider>
      <JobIndicator />
    </JobsProvider>
  );
  await screen.findByRole("button", { name: "Aviseringar, 1 pågår" });
  const polls = vi.mocked(browserApi.GET).mock.calls.length;

  await act(async () => {
    fake.latest().open();
    fake.latest().job({ ...job, task: "upload_info_blob", status: "complete" });
  });

  await screen.findByRole("button", { name: "Aviseringar" });
  expect(toast.success).toHaveBeenCalledWith("Avtal.pdf är klar och sökbar.");
  // The toaster's live region speaks it: not announced a second time.
  expect(announce).not.toHaveBeenCalled();
  // The feed is open: nothing fetched the list again to learn this.
  expect(browserApi.GET).toHaveBeenCalledTimes(polls);
  fake.restore();
});

it("finishes a crawl from the feed, refreshing its website without a poll", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  const fake = (await import("./job-events.test-support")).installFakeEventSource();
  const crawl = { ...job, task: "crawl", name: "Devize" } as Job;
  api.items = [crawl];
  const { queryClient } = renderInApp(
    <JobsProvider>
      <JobIndicator />
    </JobsProvider>
  );
  await screen.findByRole("button", { name: "Aviseringar, 1 pågår" });
  await act(async () => fake.latest().open());
  const polls = vi.mocked(browserApi.GET).mock.calls.length;
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await act(async () => fake.latest().job({ ...crawl, status: "complete" }));

  await screen.findByRole("button", { name: "Aviseringar" });
  expect(queryClient.getQueryData<Job[]>(["jobs"])).toEqual([{ ...crawl, status: "complete" }]);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["websites"] });
  expect(browserApi.GET).toHaveBeenCalledTimes(polls);
  fake.restore();
});

// The list keeps a completed job for five minutes: a job that finishes while
// the feed is down for longer is never listed with its outcome.
describe("a job that left the list while it was running", () => {
  const crawl = { ...job, id: "job-crawl", task: "crawl", name: "Devize" } as Job;
  const upload = { ...job, id: "job-upload", task: "upload_info_blob" } as Job;
  const readsById = () => callsTo("/api/v1/jobs/{id}/");

  /** Both jobs run, the feed drops, and when it is back the list has neither. */
  async function returnAfterBothLeft() {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const fake = (await import("./job-events.test-support")).installFakeEventSource();
    api.items = [crawl, upload];
    const rendered = renderInApp(
      <JobsProvider>
        <JobIndicator />
      </JobsProvider>
    );
    await screen.findByRole("button", { name: "Aviseringar, 2 pågår" });
    await act(async () => fake.latest().open());
    await act(async () => fake.latest().blip());
    api.items = [];
    const invalidate = vi.spyOn(rendered.queryClient, "invalidateQueries");
    // Ten minutes later the feed is back and the reopen reads the list again.
    await act(async () => fake.latest().open());
    return { ...rendered, fake, invalidate };
  }

  const invalidationsOf = (invalidate: { mock: { calls: unknown[][] } }, key: string) =>
    invalidate.mock.calls.filter(([filters]) => {
      const queryKey = (filters as { queryKey?: unknown[] } | undefined)?.queryKey;
      return queryKey?.length === 1 && queryKey[0] === key;
    }).length;

  it("reads each by id and reports its outcome once, as the feed would have", async () => {
    api.byId = {
      [crawl.id]: { ...crawl, status: "complete" },
      [upload.id]: { ...upload, status: "failed", failure_code: "encrypted" } as Job
    };
    const { fake, invalidate } = await returnAfterBothLeft();

    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(toast.success).toHaveBeenCalledWith("Devize är klar.");
    expect(toast.error).toHaveBeenCalledWith(
      "Avtal.pdf misslyckades.",
      expect.objectContaining({ description: expect.any(String) })
    );
    expect(invalidationsOf(invalidate, "websites")).toBe(1);
    expect(invalidationsOf(invalidate, "collections")).toBe(1);
    expect(readsById()).toHaveLength(2);

    // Nothing else left the list: the next poll reads nothing by id.
    await act(() => vi.advanceTimersByTimeAsync(120_000));
    expect(readsById()).toHaveLength(2);
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledTimes(1);
    fake.restore();
  });

  it("drops a job that was deleted meanwhile without a word", async () => {
    api.byId = { [crawl.id]: 404, [upload.id]: 404 };
    trackSyncs([{ jobId: crawl.id, knowledgeId: "ik-1" }]);
    const { fake, invalidate } = await returnAfterBothLeft();

    await vi.waitFor(() => expect(invalidationsOf(invalidate, "websites")).toBe(1));
    expect(readsById()).toHaveLength(2);
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
    // A sync that waited on the deleted job is over without another list.
    await vi.waitFor(() => expect(pendingSyncs()).toEqual([]));
    await act(() => vi.advanceTimersByTimeAsync(120_000));
    expect(readsById()).toHaveLength(2);
    fake.restore();
  });

  it("reads them together, not one after the other", async () => {
    api.byId = {
      [crawl.id]: { ...crawl, status: "complete" },
      [upload.id]: { ...upload, status: "complete" }
    };
    let answer = () => {};
    const gate = new Promise<void>((resolve) => (answer = resolve));
    api.byIdGates = { [crawl.id]: gate, [upload.id]: gate };
    trackSyncs([{ jobId: crawl.id, knowledgeId: "ik-1" }]);
    const { fake } = await returnAfterBothLeft();

    await vi.waitFor(() => expect(readsById()).toHaveLength(2));
    expect(toast.success).not.toHaveBeenCalled();
    // Not over while its read is out.
    expect(pendingSyncs()).toHaveLength(1);
    await act(async () => answer());
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledTimes(2));
    fake.restore();
  });

  it("reports a job as soon as its read answers, not when the slowest one does", async () => {
    api.byId = {
      [crawl.id]: { ...crawl, status: "complete" },
      [upload.id]: { ...upload, status: "complete" }
    };
    let answer = () => {};
    api.byIdGates = { [upload.id]: new Promise<void>((resolve) => (answer = resolve)) };
    const { fake } = await returnAfterBothLeft();

    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledWith("Devize är klar."));
    expect(toast.success).toHaveBeenCalledTimes(1);
    await act(async () => answer());
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledTimes(2));
    fake.restore();
  });
});

// A list can show a job again while its read is out, and a later list miss
// it again: only the newest read speaks for it.
describe("a job that leaves the list twice", () => {
  const crawl = { ...job, id: "job-crawl", task: "crawl", name: "Devize" } as Job;
  type Read = { resolve: (answer: Job | 404) => void; reject: (error: Error) => void };

  /** Two reads of the job are out, the first started before the second miss. */
  async function twoReadsOut() {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const reads: Read[] = [];
    api.answerById = () =>
      new Promise<Job | 404>((resolve, reject) => reads.push({ resolve, reject }));
    api.items = [crawl];
    renderInApp(
      <JobsProvider>
        <JobIndicator />
      </JobsProvider>
    );
    await screen.findByRole("button", { name: "Aviseringar, 1 pågår" });
    // Each list is waited for on screen, so the provider has judged it
    // before the next one comes.
    api.items = [];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await screen.findByRole("button", { name: "Aviseringar" });
    await vi.waitFor(() => expect(reads).toHaveLength(1));
    api.items = [crawl];
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    await screen.findByRole("button", { name: "Aviseringar, 1 pågår" });
    api.items = [];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await screen.findByRole("button", { name: "Aviseringar" });
    await vi.waitFor(() => expect(reads).toHaveLength(2));
    return reads;
  }

  it("reports the newest read's answer when the older read fails after it started", async () => {
    const [first, second] = await twoReadsOut();
    await act(async () => first!.reject(new Error("Network error")));
    await act(async () => second!.resolve({ ...crawl, status: "complete" }));

    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledWith("Devize är klar."));
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(callsTo("/api/v1/jobs/{id}/")).toHaveLength(2);
  });

  it("lets an older read neither settle nor overwrite the newest one", async () => {
    const [first, second] = await twoReadsOut();
    // Answered late, the first read would drop the job as gone.
    await act(async () => first!.resolve(404));
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Aviseringar" })).toBeTruthy();
    await act(async () => second!.resolve({ ...crawl, status: "complete" }));

    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledWith("Devize är klar."));
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(callsTo("/api/v1/jobs/{id}/")).toHaveLength(2);
  });
});

it("reads a started job by id once lists begun after it never show it", async () => {
  // It ran and finished while nothing watched, and has left the list. A list
  // already under way when the job was started cannot show it: that one waits.
  // The clock moves too: this stand-in API answers within a millisecond, and a
  // second empty list in the same one changes nothing the provider can see.
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  api.items = [];
  const started = { ...job, id: "job-new", task: "crawl", name: "Devize", status: "queued" } as Job;
  let listArrives = () => {};
  api.jobsGate = new Promise<void>((resolve) => (listArrives = resolve));
  api.byId = { [started.id]: started };
  function Track() {
    const { trackJob } = useJobs();
    return (
      <button type="button" onClick={() => trackJob(started)}>
        Track
      </button>
    );
  }
  const { queryClient } = renderInApp(
    <JobsProvider>
      <Track />
    </JobsProvider>
  );
  await vi.waitFor(() => expect(browserApi.GET).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Track" }));
  api.jobsGate = null;
  await act(async () => listArrives());
  await vi.waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([]));
  const readsById = () => callsTo("/api/v1/jobs/{id}/");
  expect(readsById()).toHaveLength(0);

  // A list begun after it: read by id, still running, so still tracked.
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  await vi.waitFor(() => expect(readsById()).toHaveLength(1));
  expect(toast.success).not.toHaveBeenCalled();

  api.byId = { [started.id]: { ...started, status: "complete" } };
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  await vi.waitFor(() => expect(toast.success).toHaveBeenCalledWith("Devize är klar."));
  expect(readsById()).toHaveLength(2);
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

it("checks the list every two minutes while the feed is open, and every 30 s once it is down", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  const fake = (await import("./job-events.test-support")).installFakeEventSource();
  api.items = [];
  // The jobs list is the only read here.
  const polls = () => vi.mocked(browserApi.GET).mock.calls.length;
  const { queryClient } = renderInApp(
    <JobsProvider>
      <JobIndicator />
    </JobsProvider>
  );
  await waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([]));
  await act(async () => fake.latest().open());
  const opened = polls();

  // The feed delivers every change: the list is only the safety net.
  await act(() => vi.advanceTimersByTimeAsync(119_000));
  expect(polls()).toBe(opened);
  await act(() => vi.advanceTimersByTimeAsync(1_000));
  expect(polls()).toBe(opened + 1);

  await act(async () => fake.latest().refuse());
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(polls()).toBe(opened + 2);
  fake.restore();
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

it("catches every job of calls made together, and checks the list once for them", async () => {
  const synced = (id: string, name: string) =>
    ({ ...job, id, name, task: "upload_info_blob", status: "complete" }) as Job;
  api.items = [synced("job-1", "Avtal.pdf"), synced("job-2", "Bilaga.pdf")];
  function Track() {
    const { trackJob } = useJobs();
    return (
      <button
        type="button"
        onClick={() => trackJob(api.items.map((item) => ({ ...item, status: "queued" })))}
      >
        Track
      </button>
    );
  }
  const { queryClient } = renderInApp(
    <JobsProvider>
      <Track />
    </JobsProvider>
  );
  await waitFor(() => expect(queryClient.getQueryData(["jobs"])).toHaveLength(2));
  const polls = vi.mocked(browserApi.GET).mock.calls.length;

  fireEvent.click(screen.getByRole("button", { name: "Track" }));

  await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(2));
  expect(toast.success).toHaveBeenCalledWith("Avtal.pdf är klar och sökbar.");
  expect(toast.success).toHaveBeenCalledWith("Bilaga.pdf är klar och sökbar.");
  expect(browserApi.GET).toHaveBeenCalledTimes(polls + 1);
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

// A faked setInterval stops Testing Library's waitFor from checking again
// until the DOM changes; these wait for state the DOM does not show.
describe("an import's first sync", () => {
  const imported = {
    id: "job-import",
    name: "Protokoll",
    task: "pull_sharepoint_content",
    status: "queued"
  } as Job;
  const pending = {
    jobId: "job-import",
    knowledgeId: "ik-1",
    name: "Protokoll",
    spaceRouteId: "space-1"
  };
  const spaceWith = (metadata: Record<string, unknown>) =>
    makeSpace({
      integrations: [
        makeIntegration({ id: "ik-1", name: "Protokoll", metadata: { size: 0, ...metadata } })
      ]
    });
  const synced = {
    last_sync_status: "success",
    last_synced_at: "2026-10-19T08:00:00Z",
    document_count: 12,
    last_sync_summary: { files_processed: 10, unchanged_items: 2, skipped_total: 1 }
  };

  function StartImport() {
    const { trackJob } = useJobs();
    return (
      <button
        type="button"
        onClick={() => {
          trackImports([pending]);
          trackJob(imported);
        }}
      >
        Importera
      </button>
    );
  }

  async function importAndFinish(status: Job["status"]) {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    api.items = [];
    const { queryClient } = renderInApp(
      <JobsProvider>
        <StartImport />
      </JobsProvider>
    );
    await vi.waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([]));
    fireEvent.click(screen.getByRole("button", { name: "Importera" }));
    api.items = [{ ...imported, status: "in progress" }];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    api.items = [{ ...imported, status }];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
  }

  it("is told with its counts and a way to the source, instead of the job's own toast", async () => {
    api.space = spaceWith(synced);
    await importAndFinish("complete");

    await vi.waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Protokoll är klar. Indexerade: 12, överhoppade: 1",
        expect.objectContaining({ action: expect.objectContaining({ label: "Visa" }) })
      )
    );
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(announce).not.toHaveBeenCalled();
    const [, options] = toast.success.mock.calls[0] as [
      string,
      { action: { onClick: () => void } }
    ];
    options.action.onClick();
    expect(router.push).toHaveBeenCalledWith("/spaces/space-1/knowledge/integrations/ik-1");
    expect(pendingImports()).toEqual([]);
  });

  it("says the first sync failed, and why", async () => {
    api.space = spaceWith({
      last_sync_status: "error",
      last_sync_attempted_at: "2026-10-19T08:00:00Z",
      last_sync_error: "Token expired"
    });
    await importAndFinish("failed");

    await vi.waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Protokoll: första synken misslyckades", {
        description: "Token expired"
      })
    );
    // Not also the job's own "Protokoll misslyckades."
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("keeps its promise across a reload: the first list judges an import from an earlier page", async () => {
    sessionStorage.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify([pending]));
    resetPendingImports();
    // Its job is no longer listed at all.
    api.items = [];
    api.space = spaceWith(synced);

    renderInApp(<JobsProvider>{null}</JobsProvider>);

    await vi.waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Protokoll är klar. Indexerade: 12, överhoppade: 1",
        expect.anything()
      )
    );
    expect(sessionStorage.getItem(PENDING_IMPORTS_STORAGE_KEY)).toBeNull();
  });

  it("retries an unchanged completed job until its sync status becomes visible", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    sessionStorage.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify([pending]));
    resetPendingImports();
    api.items = [{ ...imported, status: "complete" }];
    api.space = spaceWith({ last_sync_status: "never" });

    renderInApp(<JobsProvider>{null}</JobsProvider>);

    await vi.waitFor(() =>
      expect(browserApi.GET).toHaveBeenCalledWith("/api/v1/spaces/{id}/", expect.anything())
    );
    await act(async () => {});
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
    expect(pendingImports()).toEqual([{ ...pending, jobStatus: "complete" }]);
    api.space = spaceWith(synced);
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(pendingImports()).toEqual([]);
  });

  it("keeps a recovered job's status for reports after a list that no longer shows it", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    sessionStorage.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify([pending]));
    resetPendingImports();
    api.items = [{ ...imported, status: "in progress" }];
    api.space = spaceWith({ last_sync_status: "never" });
    const { queryClient } = renderInApp(<JobsProvider>{null}</JobsProvider>);
    await vi.waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual(api.items));

    // It finished unseen and left the list; its read says complete, but its
    // sync status is not written yet: the report waits.
    api.items = [];
    api.byId = { [imported.id]: { ...imported, status: "complete" } };
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await vi.waitFor(() =>
      expect(browserApi.GET).toHaveBeenCalledWith("/api/v1/spaces/{id}/", expect.anything())
    );
    await act(async () => {});
    // The next list no longer shows it at all: still a completed job.
    const spaceReads = () => callsTo("/api/v1/spaces/{id}/").length;
    const before = spaceReads();
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    await vi.waitFor(() => expect(spaceReads()).toBeGreaterThan(before));
    await act(async () => {});
    expect(toast.error).not.toHaveBeenCalled();
    expect(pendingImports()).toHaveLength(1);

    api.space = spaceWith(synced);
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("retries a temporary space-read failure without another job transition", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    sessionStorage.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify([pending]));
    resetPendingImports();
    api.items = [{ ...imported, status: "complete" }];
    api.space = spaceWith(synced);
    api.spaceError = new Error("temporary outage");
    renderInApp(<JobsProvider>{null}</JobsProvider>);
    await vi.waitFor(() => expect(logged).toHaveBeenCalled());
    api.spaceError = null;
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(pendingImports()).toEqual([]);
    logged.mockRestore();
  });

  it("is not taken for failed when a pushed update for another job comes before the first list", async () => {
    const fake = (await import("./job-events.test-support")).installFakeEventSource();
    sessionStorage.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify([pending]));
    resetPendingImports();
    trackSyncs([{ jobId: "job-sync", knowledgeId: "ik-2" }]);
    api.space = spaceWith({ last_sync_status: "never" });
    let listArrives = () => {};
    api.jobsGate = new Promise<void>((resolve) => (listArrives = resolve));
    const running = [
      { ...imported, status: "in progress" },
      { ...imported, id: "job-sync", status: "in progress" },
      job
    ] as Job[];
    api.items = running;
    const { queryClient } = renderInApp(<JobsProvider>{null}</JobsProvider>);

    await act(async () => {
      fake.latest().open();
      fake.latest().job(job);
    });
    expect(queryClient.getQueryData(["jobs"])).toEqual([job]);
    await act(async () => listArrives());
    await vi.waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual(running));
    await act(async () => {});

    expect(toast.error).not.toHaveBeenCalled();
    expect(pendingImports()).toEqual([pending]);
    expect(pendingSyncs()).toHaveLength(1);
    fake.restore();
  });

  it("does not repeat a restored import result after a second reload", async () => {
    sessionStorage.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify([pending]));
    resetPendingImports();
    api.items = [{ ...imported, status: "complete" }];
    api.space = spaceWith(synced);
    const first = renderInApp(<JobsProvider>{null}</JobsProvider>);
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    first.unmount();
    resetPendingImports();
    const second = renderInApp(<JobsProvider>{null}</JobsProvider>);
    await waitFor(() => expect(second.queryClient.getQueryData(["jobs"])).toEqual(api.items));
    expect(toast.success).toHaveBeenCalledTimes(1);
  });
});

it("stops a sync queued from a menu reading as queued once its job is over, not before it is listed", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  api.items = [];
  const sync = { ...job, id: "job-sync", name: "Avtal", task: "pull_sharepoint_content" };
  // Asked by id, the server knows it: still queued.
  api.byId = { "job-sync": { ...sync, status: "queued" } as Job };
  function StartSync() {
    const { trackJob } = useJobs();
    return (
      <button
        type="button"
        onClick={() => {
          trackSyncs([{ jobId: "job-sync", knowledgeId: "i1" }]);
          trackJob({ ...sync, status: "queued" } as Job);
        }}
      >
        Synka
      </button>
    );
  }
  const { queryClient } = renderInApp(
    <JobsProvider>
      <StartSync />
    </JobsProvider>
  );
  await vi.waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([]));

  fireEvent.click(screen.getByRole("button", { name: "Synka" }));
  // The list read right after does not show the job yet.
  await vi.waitFor(() => expect(callsTo("/api/v1/jobs/")).toHaveLength(2));
  await vi.waitFor(() => expect(callsTo("/api/v1/jobs/{id}/")).toHaveLength(1));
  await act(async () => {});
  expect(pendingSyncs()).toHaveLength(1);

  api.items = [{ ...sync, status: "failed" } as Job];
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  await vi.waitFor(() => expect(pendingSyncs()).toEqual([]));
});

/** Whether the browser would ask before unloading the page now. */
function unloadIsGuarded(): boolean {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

/** An upload request that answers when the test says so. */
class UploadRequest {
  static sent: UploadRequest[] = [];
  status = 0;
  response: unknown = null;
  responseType = "";
  upload = { addEventListener: () => {} };
  private listeners = new Map<string, () => void>();
  open() {}
  getAllResponseHeaders() {
    return "content-type: application/json\r\n";
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, listener);
  }
  send() {
    UploadRequest.sent.push(this);
  }
  answer(status: number, response: unknown) {
    this.status = status;
    this.response = response;
    this.listeners.get("load")?.();
    this.listeners.get("loadend")?.();
  }
}

it("warns before a reload loses a queued or running upload, until every upload is over", async () => {
  UploadRequest.sent = [];
  vi.stubGlobal("XMLHttpRequest", UploadRequest);
  function Queue() {
    const { queueUploads } = useJobs();
    return (
      <button
        type="button"
        onClick={() =>
          queueUploads("collection-1", [new File(["a"], "a.pdf"), new File(["b"], "b.pdf")])
        }
      >
        Queue
      </button>
    );
  }
  try {
    renderInApp(
      <JobsProvider>
        <Queue />
      </JobsProvider>
    );
    expect(unloadIsGuarded()).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Queue" }));
    await waitFor(() => expect(UploadRequest.sent).toHaveLength(2));
    expect(unloadIsGuarded()).toBe(true);

    act(() => UploadRequest.sent[0]!.answer(200, { ...job, id: "job-a" }));
    await waitFor(() => expect(toast.info).toHaveBeenCalledTimes(1));
    expect(unloadIsGuarded()).toBe(true);

    // A failed upload is over too: nothing is left to lose.
    act(() => UploadRequest.sent[1]!.answer(500, { message: "Lagringen är full" }));
    await waitFor(() => expect(unloadIsGuarded()).toBe(false));
  } finally {
    vi.unstubAllGlobals();
  }
});
