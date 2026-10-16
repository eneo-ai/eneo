import type { IntegrationKnowledge, Job } from "@eneo/eneo-js";
import { get } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { pendingImports, type PendingImport } from "../importCompletion";

type CompletionEvent = { timestamp: number; jobId: string } | null;
type Space = { id: string; knowledge: { integrationKnowledge: IntegrationKnowledge[] } };

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
  refreshCurrentSpace: vi.fn(async () => {}),
  jobs: [] as Pick<Job, "id" | "status">[]
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
      }
    },
    getJobManager: () => ({
      state: {
        jobs: {
          subscribe(run: (jobs: Pick<Job, "id" | "status">[]) => void) {
            run(api.jobs);
            return () => undefined;
          }
        }
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
  return { id, knowledge: { integrationKnowledge: items } };
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
  beforeEach(() => {
    api.goto.mockClear();
    api.toastSuccess.mockClear();
    api.toastError.mockClear();
    api.refreshCurrentSpace.mockReset().mockImplementation(async () => {});
    api.jobs = [];
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
      `${m.integration_import_failed_toast({ name: "Arkiv" })}: 403 Forbidden`
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
      m.integration_import_failed_toast({ name: "Arkiv" })
    );
    expect(get(pendingImports)).toEqual([]);
  });

  it("keeps an import pending while another space is current and reports it on return", async () => {
    const item = pending("job-1", "ik-1", "Protokoll 2026");
    pendingImports.set([item]);
    api.jobs = [{ id: "job-1", status: "complete" }];
    spaces.currentSpace.set(space("space-2"));
    // The real refresh publishes a new space object with the same id.
    api.refreshCurrentSpace.mockImplementation(async () => {
      spaces.currentSpace.set({ ...get(spaces.currentSpace) });
    });
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });
    await settle();

    // Once on mount and once for the event; the refreshes themselves queue nothing.
    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(2);
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
    expect(api.refreshCurrentSpace).toHaveBeenCalledTimes(3);
  });
});
