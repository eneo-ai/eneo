import type { IntegrationKnowledge, Job } from "@eneo/eneo-js";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { pendingImports } from "../importCompletion";

type CompletionEvent = { timestamp: number; jobId: string } | null;

const api = vi.hoisted(() => ({
  goto: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  refreshCurrentSpace: vi.fn(async () => {}),
  jobs: [] as Pick<Job, "id" | "status">[],
  space: { id: "space-1", knowledge: { integrationKnowledge: [] as IntegrationKnowledge[] } }
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
    state: {
      currentSpace: {
        subscribe(run: (space: typeof api.space) => void) {
          run(api.space);
          return () => undefined;
        }
      }
    }
  })
}));

import { jobCompletionEvents } from "$lib/features/jobs/JobManager";
import ImportCompletionToasts from "./ImportCompletionToasts.svelte";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function knowledge(id: string, name: string, metadata: Partial<Metadata>): IntegrationKnowledge {
  return {
    id,
    name,
    space_id: "space-1",
    metadata: { size: 0, ...metadata }
  } as IntegrationKnowledge;
}

const events = jobCompletionEvents as unknown as { set: (event: CompletionEvent) => void };

describe("ImportCompletionToasts", () => {
  beforeEach(() => {
    api.goto.mockClear();
    api.toastSuccess.mockClear();
    api.toastError.mockClear();
    api.refreshCurrentSpace.mockClear();
    api.jobs = [];
    api.space.knowledge.integrationKnowledge = [];
    pendingImports.set([]);
    events.set(null);
  });

  it("reports indexed and skipped counts with a link once the import's job completes", async () => {
    pendingImports.set([
      { jobId: "job-1", knowledgeId: "ik-1", name: "Protokoll 2026", spaceRouteId: "space-1" },
      { jobId: "job-2", knowledgeId: "ik-2", name: "Rutiner", spaceRouteId: "space-1" }
    ]);
    api.jobs = [
      { id: "job-1", status: "complete" },
      { id: "job-2", status: "in progress" }
    ];
    api.space.knowledge.integrationKnowledge = [
      knowledge("ik-1", "Protokoll 2026", {
        last_sync_status: "success",
        document_count: 12,
        last_sync_summary: { files_processed: 12, unchanged_items: 0, skipped_total: 2 }
      }),
      knowledge("ik-2", "Rutiner", { last_sync_status: "never" })
    ];
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
    expect(pendingImports).toBeDefined();
    await vi.waitFor(() => expect(api.toastError).not.toHaveBeenCalled());
  });

  it("reports a failed first sync with its error and stops tracking the job", async () => {
    pendingImports.set([
      { jobId: "job-1", knowledgeId: "ik-1", name: "Arkiv", spaceRouteId: "space-1" }
    ]);
    api.jobs = [{ id: "job-1", status: "failed" }];
    api.space.knowledge.integrationKnowledge = [
      knowledge("ik-1", "Arkiv", { last_sync_status: "error", last_sync_error: "403 Forbidden" })
    ];
    render(ImportCompletionToasts);

    events.set({ timestamp: Date.now(), jobId: "any" });

    await vi.waitFor(() => expect(api.toastError).toHaveBeenCalledTimes(1));
    expect(api.toastError).toHaveBeenCalledWith(
      `${m.integration_import_failed_toast({ name: "Arkiv" })}: 403 Forbidden`
    );
    expect(api.toastSuccess).not.toHaveBeenCalled();

    events.set({ timestamp: Date.now() + 1, jobId: "any" });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.toastError).toHaveBeenCalledTimes(1);
  });
});
