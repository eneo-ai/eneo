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

const job = { id: "job-1", name: "Avtal.pdf", status: "in progress" } as Job;
const api = vi.hoisted(() => ({
  items: [] as Job[],
  space: null as unknown,
  spaceError: null as Error | null,
  /** While set, the jobs list waits for it. */
  jobsGate: null as Promise<void> | null
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string) => {
      if (path === "/api/v1/spaces/{id}/" && api.spaceError) throw api.spaceError;
      if (path === "/api/v1/jobs/" && api.jobsGate) await api.jobsGate;
      return {
        data: path === "/api/v1/spaces/{id}/" ? api.space : { items: api.items },
        response: new Response("{}")
      };
    })
  }
}));

beforeEach(() => {
  api.items = [job];
  api.spaceError = null;
  api.jobsGate = null;
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
    expect(pendingImports()).toEqual([pending]);
    api.space = spaceWith(synced);
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(pendingImports()).toEqual([]);
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
  await vi.waitFor(() => expect(browserApi.GET).toHaveBeenCalledTimes(2));
  await act(async () => {});
  expect(pendingSyncs()).toHaveLength(1);

  api.items = [{ ...sync, status: "failed" } as Job];
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  await vi.waitFor(() => expect(pendingSyncs()).toEqual([]));
});
