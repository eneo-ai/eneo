import type { IntegrationKnowledge, Job } from "@eneo/eneo-js";
import { get } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { pendingImports, type PendingImport } from "../importCompletion";

type CompletionEvent = { timestamp: number; jobId: string } | null;
type Space = {
  id: string;
  routeId: string;
  knowledge: { integrationKnowledge: IntegrationKnowledge[] };
};

function store<T>(initial: T) {
  let value = initial;
  const subscribers = new Set<(value: T) => void>();
  return {
    subscribe(run: (value: T) => void) {
      subscribers.add(run);
      run(value);
      return () => subscribers.delete(run);
    },
    set(next: T) {
      value = next;
      subscribers.forEach((run) => run(value));
    }
  };
}

const api = vi.hoisted(() => ({
  goto: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  refreshCurrentSpace: vi.fn(async () => true),
  jobs: [] as Pick<Job, "id" | "status">[],
  jobSubscribers: new Set<(jobs: Pick<Job, "id" | "status">[]) => void>(),
  jobsLoaded: (() => {
    let value = true;
    const subscribers = new Set<(loaded: boolean) => void>();
    return {
      subscribe(run: (loaded: boolean) => void) {
        subscribers.add(run);
        run(value);
        return () => subscribers.delete(run);
      },
      set(next: boolean) {
        value = next;
        subscribers.forEach((run) => run(value));
      }
    };
  })()
}));

vi.mock("$app/navigation", () => ({ goto: api.goto }));
vi.mock("$lib/components/toast", () => ({
  toast: { success: api.toastSuccess, error: api.toastError, warning: vi.fn() }
}));
vi.mock("$lib/features/jobs/JobManager", () => {
  let value: CompletionEvent = null;
  const subscribers = new Set<(event: CompletionEvent) => void>();
  return {
    jobCompletionEvents: {
      subscribe(run: (event: CompletionEvent) => void) {
        subscribers.add(run);
        run(value);
        return () => subscribers.delete(run);
      },
      set(next: CompletionEvent) {
        value = next;
        subscribers.forEach((run) => run(value));
        api.jobSubscribers.forEach((run) => run(api.jobs));
      }
    },
    getJobManager: () => ({
      state: {
        jobs: {
          subscribe(run: (jobs: Pick<Job, "id" | "status">[]) => void) {
            api.jobSubscribers.add(run);
            run(api.jobs);
            return () => api.jobSubscribers.delete(run);
          }
        },
        jobsLoaded: api.jobsLoaded
      }
    })
  };
});
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    refreshCurrentSpace: api.refreshCurrentSpace,
    state: { currentSpace: spaces.currentSpace }
  })
}));

import { jobCompletionEvents } from "$lib/features/jobs/JobManager";
import ImportCompletionToasts from "./ImportCompletionToasts.svelte";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function knowledge(
  id: string,
  name: string,
  metadata: Partial<Metadata>,
  spaceId = "space-1"
): IntegrationKnowledge {
  return {
    id,
    name,
    space_id: spaceId,
    metadata: { size: 0, ...metadata }
  } as IntegrationKnowledge;
}

function space(id: string, items: IntegrationKnowledge[] = []): Space {
  return { id, routeId: id, knowledge: { integrationKnowledge: items } };
}

function pending(jobId: string, knowledgeId: string, name: string): PendingImport {
  return { jobId, knowledgeId, name, spaceRouteId: "space-1" };
}

const spaces = { currentSpace: store<Space>(space("space-1")) };
const events = jobCompletionEvents as unknown as { set: (event: CompletionEvent) => void };

function settle() {
  return new Promise((resolve) => setTimeout(resolve, 20));
}

describe("ImportCompletionToasts", () => {
  afterEach(() => vi.useRealTimers());
  beforeEach(() => {
    api.goto.mockClear();
    api.toastSuccess.mockClear();
    api.toastError.mockClear();
    api.refreshCurrentSpace.mockReset().mockImplementation(async () => true);
    api.jobs = [];
    api.jobsLoaded.set(true);
    spaces.currentSpace.set(space("space-1"));
    pendingImports.set([]);
    events.set(null);
  });

  it("reports indexed and skipped counts with a link once the import's job completes", async () => {
    const running = pending("job-2", "ik-2", "Rutiner");
    pendingImports.set([pending("job-1", "ik-1", "Protokoll 2026"), running]);
    api.jobs = [
      { id: "job-1", status: "complete" },
      { id: "job-2", status: "in progress" }
    ];
    spaces.currentSpace.set(
      space("space-1", [
        knowledge("ik-1", "Protokoll 2026", {
          last_sync_status: "success",
          document_count: 12,
          last_sync_summary: { files_processed: 12, unchanged_items: 0, skipped_total: 2 }
        }),
        knowledge("ik-2", "Rutiner", { last_sync_status: "never" })
      ])
    );
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });

    await vi.waitFor(() => expect(api.toastSuccess).toHaveBeenCalledTimes(1));
    expect(api.refreshCurrentSpace).toHaveBeenCalledWith("knowledge");
    const [message, options] = api.toastSuccess.mock.calls[0];
    expect(message).toBe(
      m.integration_import_result_toast({ name: "Protokoll 2026", indexed: 12, skipped: 2 })
    );
    expect(options.duration).toBe(15_000);
    expect(options.action.label).toBe(m.show());
    options.action.onClick();
    expect(api.goto).toHaveBeenCalledWith("/spaces/space-1/knowledge/integrations/ik-1");
    expect(api.toastError).not.toHaveBeenCalled();
    expect(get(pendingImports)).toEqual([running]);

    // A reported import is not reported again on the next event.
    events.set({ timestamp: Date.now() + 1, jobId: "any" });
    await settle();
    expect(api.toastSuccess).toHaveBeenCalledTimes(1);
  });

  it("reports a failed first sync with its error and stops tracking the job", async () => {
    pendingImports.set([pending("job-1", "ik-1", "Arkiv")]);
    api.jobs = [{ id: "job-1", status: "failed" }];
    spaces.currentSpace.set(
      space("space-1", [
        knowledge("ik-1", "Arkiv", { last_sync_status: "error", last_sync_error: "403 Forbidden" })
      ])
    );
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });

    await vi.waitFor(() => expect(api.toastError).toHaveBeenCalledTimes(1));
    expect(api.toastError).toHaveBeenCalledWith(
      `${m.integration_import_failed_toast({ name: "Arkiv" })}: 403 Forbidden`,
      { duration: 15_000 }
    );
    expect(api.toastSuccess).not.toHaveBeenCalled();
    expect(get(pendingImports)).toEqual([]);

    events.set({ timestamp: Date.now() + 1, jobId: "any" });
    await settle();
    expect(api.toastError).toHaveBeenCalledTimes(1);
  });

  it("reports a job that failed before the sync wrote a status", async () => {
    pendingImports.set([pending("job-1", "ik-1", "Arkiv")]);
    api.jobs = [{ id: "job-1", status: "failed" }];
    spaces.currentSpace.set(
      space("space-1", [knowledge("ik-1", "Arkiv", { last_sync_status: "never" })])
    );
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });

    await vi.waitFor(() => expect(api.toastError).toHaveBeenCalledTimes(1));
    expect(api.toastError).toHaveBeenCalledWith(
      m.integration_import_failed_toast({ name: "Arkiv" }),
      {
        duration: 15_000
      }
    );
    expect(get(pendingImports)).toEqual([]);
  });

  it("reports an import of several folders in one notice once all of them have synced", async () => {
    const batch = (jobId: string, id: string, name: string): PendingImport => ({
      ...pending(jobId, id, name),
      batchId: "job-1",
      batchName: "Nämnder"
    });
    pendingImports.set([batch("job-1", "ik-1", "Bygg"), batch("job-2", "ik-2", "Miljö")]);
    api.jobs = [
      { id: "job-1", status: "complete" },
      { id: "job-2", status: "in progress" }
    ];
    const synced = (id: string, name: string, processed: number) => ({
      ...knowledge(id, name, {
        last_sync_status: "success",
        last_sync_summary: { files_processed: processed, unchanged_items: 0, skipped_total: 1 }
      }),
      wrapper_id: "w-1"
    });
    spaces.currentSpace.set(
      space("space-1", [synced("ik-1", "Bygg", 4), synced("ik-2", "Miljö", 6)])
    );
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "job-1" });
    await settle();
    expect(api.toastSuccess).not.toHaveBeenCalled();

    api.jobs = [
      { id: "job-1", status: "complete" },
      { id: "job-2", status: "complete" }
    ];
    events.set({ timestamp: Date.now() + 1, jobId: "job-2" });

    await vi.waitFor(() => expect(api.toastSuccess).toHaveBeenCalledTimes(1));
    const [message, options] = api.toastSuccess.mock.calls[0];
    expect(message).toBe(
      m.integration_import_batch_result_toast({
        name: "Nämnder",
        count: 2,
        indexed: 10,
        skipped: 2
      })
    );
    options.action.onClick();
    expect(api.goto).toHaveBeenCalledWith("/spaces/space-1/knowledge/integrations/wrapper/w-1");
    expect(get(pendingImports)).toEqual([]);
  });

  it("says how many folders of an import failed, and why when they share a sign-in failure", async () => {
    const batch = (jobId: string, id: string, name: string): PendingImport => ({
      ...pending(jobId, id, name),
      batchId: "job-1",
      batchName: "Nämnder"
    });
    pendingImports.set([
      batch("job-1", "ik-1", "Bygg"),
      batch("job-2", "ik-2", "Miljö"),
      batch("job-3", "ik-3", "Skola")
    ]);
    api.jobs = ["job-1", "job-2", "job-3"].map((id) => ({ id, status: "complete" as const }));
    const signIn = "SharePoint credentials are invalid or expired: AADSTS7000222";
    spaces.currentSpace.set(
      space("space-1", [
        knowledge("ik-1", "Bygg", { last_sync_status: "error", last_sync_error: signIn }),
        knowledge("ik-2", "Miljö", { last_sync_status: "success", document_count: 3 }),
        knowledge("ik-3", "Skola", { last_sync_status: "error", last_sync_error: signIn })
      ])
    );
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "job-3" });

    await vi.waitFor(() => expect(api.toastError).toHaveBeenCalledTimes(1));
    const [message, options] = api.toastError.mock.calls[0];
    expect(message).toBe(
      `${m.integration_import_batch_failed_toast({ name: "Nämnder", failed: 2, count: 3 })}: ${m.integration_source_stopped_sign_in_description()}`
    );
    options.action.onClick();
    expect(api.goto).toHaveBeenCalledWith("/spaces/space-1/knowledge?tab=integrations");
    expect(api.toastSuccess).not.toHaveBeenCalled();
  });

  it("keeps an import pending while another space is current and reports it on return", async () => {
    const item = pending("job-1", "ik-1", "Protokoll 2026");
    pendingImports.set([item]);
    api.jobs = [{ id: "job-1", status: "complete" }];
    spaces.currentSpace.set(space("space-2"));
    // The real refresh publishes a new space object with the same id.
    api.refreshCurrentSpace.mockImplementation(async () => {
      spaces.currentSpace.set({ ...get(spaces.currentSpace) });
      return true;
    });
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });
    await settle();

    // The item cannot be looked up from here, so the other space is left alone.
    expect(api.refreshCurrentSpace).not.toHaveBeenCalled();
    expect(api.toastSuccess).not.toHaveBeenCalled();
    expect(api.toastError).not.toHaveBeenCalled();
    expect(get(pendingImports)).toEqual([item]);

    spaces.currentSpace.set(
      space("space-1", [
        knowledge("ik-1", "Protokoll 2026", {
          last_sync_status: "success",
          document_count: 3,
          last_sync_summary: { files_processed: 3, unchanged_items: 0, skipped_total: 0 }
        })
      ])
    );

    await vi.waitFor(() => expect(api.toastSuccess).toHaveBeenCalledTimes(1));
    expect(api.toastSuccess.mock.calls[0][0]).toBe(
      m.integration_import_result_toast({ name: "Protokoll 2026", indexed: 3, skipped: 0 })
    );
    expect(get(pendingImports)).toEqual([]);
    await settle();
    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(1);
  });

  it("forgets an import whose item was deleted from its space", async () => {
    pendingImports.set([pending("job-1", "ik-1", "Arkiv")]);
    api.jobs = [];
    spaces.currentSpace.set(space("space-1", [knowledge("ik-2", "Annat", {})]));
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });

    await vi.waitFor(() => expect(get(pendingImports)).toEqual([]));
    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(1);
    expect(api.toastSuccess).not.toHaveBeenCalled();
    expect(api.toastError).not.toHaveBeenCalled();

    // Nothing is left to refresh for on the next event.
    events.set({ timestamp: Date.now() + 1, jobId: "any" });
    await settle();
    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(1);
  });

  it("keeps an import pending when the space could not be refreshed", async () => {
    const item = pending("job-1", "ik-1", "Arkiv");
    pendingImports.set([item]);
    api.jobs = [{ id: "job-1", status: "complete" }];
    // The store still predates the import: without a refresh the item looks deleted.
    spaces.currentSpace.set(space("space-1"));
    api.refreshCurrentSpace.mockImplementation(async () => false);
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });
    await vi.waitFor(() => expect(api.refreshCurrentSpace).toHaveBeenCalled());
    await settle();
    expect(get(pendingImports)).toEqual([item]);
    expect(api.toastSuccess).not.toHaveBeenCalled();

    api.refreshCurrentSpace.mockImplementation(async () => {
      spaces.currentSpace.set(
        space("space-1", [
          knowledge("ik-1", "Arkiv", {
            last_sync_status: "success",
            document_count: 2,
            last_sync_summary: { files_processed: 2, unchanged_items: 0, skipped_total: 0 }
          })
        ])
      );
      return true;
    });
    events.set({ timestamp: Date.now() + 1, jobId: "any" });

    await vi.waitFor(() => expect(api.toastSuccess).toHaveBeenCalledTimes(1));
    expect(get(pendingImports)).toEqual([]);
  });

  it("goes on reporting after a run that threw", async () => {
    pendingImports.set([pending("job-1", "ik-1", "Arkiv")]);
    api.jobs = [{ id: "job-1", status: "complete" }];
    spaces.currentSpace.set(
      space("space-1", [
        knowledge("ik-1", "Arkiv", {
          last_sync_status: "success",
          document_count: 1,
          last_sync_summary: { files_processed: 1, unchanged_items: 0, skipped_total: 0 }
        })
      ])
    );
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    api.refreshCurrentSpace.mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      throw new Error("boom");
    });
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });
    await vi.waitFor(() => expect(consoleError).toHaveBeenCalled());
    await settle();
    expect(api.toastSuccess).not.toHaveBeenCalled();

    // The chain is intact: the next run goes through once the refresh works again.
    api.refreshCurrentSpace.mockImplementation(async () => true);
    events.set({ timestamp: Date.now() + 1, jobId: "any" });
    await vi.waitFor(() => expect(api.toastSuccess).toHaveBeenCalledTimes(1));
    consoleError.mockRestore();
  });

  it("judges an import kept from an earlier page load by the first job list", async () => {
    pendingImports.set([pending("job-1", "ik-1", "Protokoll 2026")]);
    api.jobsLoaded.set(false);
    api.jobs = [];
    spaces.currentSpace.set(
      space("space-1", [
        knowledge("ik-1", "Protokoll 2026", {
          last_sync_status: "success",
          document_count: 4,
          last_sync_summary: { files_processed: 4, unchanged_items: 0, skipped_total: 0 }
        })
      ])
    );
    render(ImportCompletionToasts);
    await settle();

    // A job missing from a list that has not arrived yet has not finished.
    expect(api.refreshCurrentSpace).not.toHaveBeenCalled();
    expect(api.toastSuccess).not.toHaveBeenCalled();

    api.jobs = [{ id: "job-1", status: "complete" }];
    api.jobsLoaded.set(true);

    await vi.waitFor(() => expect(api.toastSuccess).toHaveBeenCalledTimes(1));
    expect(api.toastSuccess.mock.calls[0][0]).toBe(
      m.integration_import_result_toast({ name: "Protokoll 2026", indexed: 4, skipped: 0 })
    );
    expect(get(pendingImports)).toEqual([]);
  });

  it("retries a settled import after a read failure even when job polling has stopped", async () => {
    vi.useFakeTimers();
    const item = pending("job-1", "ik-1", "Arkiv");
    pendingImports.set([item]);
    api.jobs = [{ id: "job-1", status: "complete" }];
    spaces.currentSpace.set(
      space("space-1", [
        knowledge("ik-1", "Arkiv", {
          last_sync_status: "success",
          document_count: 2,
          last_sync_summary: { files_processed: 2, unchanged_items: 0, skipped_total: 0 }
        })
      ])
    );
    api.refreshCurrentSpace.mockResolvedValueOnce(false).mockResolvedValue(true);
    render(ImportCompletionToasts);
    await vi.advanceTimersByTimeAsync(0);
    expect(api.toastSuccess).not.toHaveBeenCalled();
    expect(get(pendingImports)).toEqual([item]);
    // No completion event, space change or new jobs list arrives.
    await vi.advanceTimersByTimeAsync(2_000);
    expect(api.toastSuccess).toHaveBeenCalledTimes(1);
    expect(get(pendingImports)).toEqual([]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(api.toastSuccess).toHaveBeenCalledTimes(1);
  });

  it("does not report or forget an import after navigating away during its refresh", async () => {
    const item = pending("job-1", "ik-1", "Arkiv");
    pendingImports.set([item]);
    api.jobs = [{ id: "job-1", status: "complete" }];
    let finish!: (value: boolean) => void;
    api.refreshCurrentSpace.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    render(ImportCompletionToasts);
    await vi.waitFor(() => expect(api.refreshCurrentSpace).toHaveBeenCalled());
    spaces.currentSpace.set(space("space-2"));
    finish(false);
    await settle();
    expect(get(pendingImports)).toEqual([item]);
    expect(api.toastSuccess).not.toHaveBeenCalled();
    expect(api.toastError).not.toHaveBeenCalled();
  });
});
