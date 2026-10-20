import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const api = vi.hoisted(() => ({
  triggerFullSync: vi.fn(),
  refreshCurrentSpace: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  addJob: vi.fn(),
  startFastUpdatePolling: vi.fn()
}));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ integrations: { knowledge: { triggerFullSync: api.triggerFullSync } } })
}));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    refreshCurrentSpace: api.refreshCurrentSpace,
    state: {
      currentSpace: {
        subscribe: (run: (space: { id: string }) => void) => {
          run({ id: "space-1" });
          return () => undefined;
        }
      }
    }
  })
}));
vi.mock("$lib/components/toast", () => ({
  toast: { success: api.toastSuccess, error: api.toastError, warning: vi.fn() }
}));

vi.mock("$lib/features/jobs/JobManager", () => ({
  getJobManager: () => ({
    addJob: api.addJob,
    startFastUpdatePolling: api.startFastUpdatePolling
  })
}));

import { get } from "svelte/store";
import { pendingSyncs } from "$lib/features/integrations/pendingSyncs";
import SharePointWrapperActions from "./SharePointWrapperActions.svelte";

const jobFor = ({ knowledge }: { knowledge: IntegrationKnowledge }) =>
  Promise.resolve({ id: `job-${knowledge.id}`, status: "queued" });

function item(id: string): IntegrationKnowledge {
  return {
    id,
    name: `Item ${id}`,
    integration_type: "sharepoint",
    permissions: ["edit", "delete"]
  } as unknown as IntegrationKnowledge;
}

const items = ["a", "b", "c", "d", "e"].map(item);

async function openResyncDialog() {
  await page.getByRole("button", { name: m.actions() }).click();
  await page.getByRole("menuitem", { name: m.resync_all_wrapper() }).click();
  await expect.element(page.getByRole("alertdialog")).toBeVisible();
}

async function confirmResync() {
  await page.getByRole("button", { name: m.start_full_sync() }).click();
  await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
}

describe("SharePointWrapperActions resync all", () => {
  beforeEach(() => {
    api.triggerFullSync.mockReset();
    api.refreshCurrentSpace.mockClear();
    api.toastSuccess.mockClear();
    api.toastError.mockClear();
    api.addJob.mockClear();
    api.startFastUpdatePolling.mockClear();
    pendingSyncs.set([]);
    render(SharePointWrapperActions, {
      wrapperId: "w-1",
      wrapperName: "Intranet",
      itemCount: items.length,
      items,
      canEdit: true,
      canDelete: true
    });
  });

  it("queues one full sync per item and reports success", async () => {
    api.triggerFullSync.mockImplementation(jobFor);
    await openResyncDialog();
    await confirmResync();

    expect(api.triggerFullSync).toHaveBeenCalledTimes(items.length);
    // Each item reads as queued until the worker reports on it or its job ends.
    expect(api.addJob).toHaveBeenCalledTimes(items.length);
    expect(api.startFastUpdatePolling).toHaveBeenCalledOnce();
    expect(get(pendingSyncs).map(({ jobId, knowledgeId }) => ({ jobId, knowledgeId }))).toEqual(
      items.map((item) => ({ jobId: `job-${item.id}`, knowledgeId: item.id }))
    );
    expect(api.toastSuccess).toHaveBeenCalledWith(
      m.resync_all_wrapper_queued({ count: items.length })
    );
    expect(api.toastError).not.toHaveBeenCalled();
  });

  it("names the failed count, closes the dialog and only re-queues on a new confirm", async () => {
    api.triggerFullSync.mockImplementation(({ knowledge }: { knowledge: IntegrationKnowledge }) =>
      knowledge.id === "b" || knowledge.id === "d"
        ? Promise.reject(new Error("boom"))
        : jobFor({ knowledge })
    );
    await openResyncDialog();
    await confirmResync();

    expect(api.triggerFullSync).toHaveBeenCalledTimes(items.length);
    expect(api.toastError).toHaveBeenCalledWith(
      m.resync_all_wrapper_partial_failure({
        failed: 2,
        total: items.length,
        names: "Item b, Item d"
      })
    );
    expect(api.refreshCurrentSpace).toHaveBeenCalledOnce();
    expect(api.toastSuccess).not.toHaveBeenCalled();
    expect(get(pendingSyncs).map((pending) => pending.knowledgeId)).toEqual(["a", "c", "e"]);

    await openResyncDialog();
    expect(api.triggerFullSync).toHaveBeenCalledTimes(items.length);

    await confirmResync();
    expect(api.triggerFullSync).toHaveBeenCalledTimes(items.length * 2);
  });

  it("sends a few at a time", async () => {
    let inFlight = 0;
    let most = 0;
    api.triggerFullSync.mockImplementation(
      async ({ knowledge }: { knowledge: IntegrationKnowledge }) => {
        inFlight += 1;
        most = Math.max(most, inFlight);
        await new Promise((resolve) => setTimeout(resolve, 10));
        inFlight -= 1;
        return jobFor({ knowledge });
      }
    );
    await openResyncDialog();
    await confirmResync();

    expect(api.triggerFullSync).toHaveBeenCalledTimes(items.length);
    expect(most).toBe(4);
  });
});

describe("SharePointWrapperActions with many folders", () => {
  it("names the first few failed folders and only counts the rest", async () => {
    const many = Array.from({ length: 8 }, (_, index) => item(`f${index}`));
    api.triggerFullSync.mockReset().mockRejectedValue(new Error("boom"));
    api.toastError.mockClear();
    render(SharePointWrapperActions, {
      wrapperId: "w-2",
      wrapperName: "Arkiv",
      itemCount: many.length,
      items: many,
      canEdit: true,
      canDelete: true
    });
    await openResyncDialog();
    await confirmResync();

    expect(api.toastError).toHaveBeenCalledWith(
      m.resync_all_wrapper_partial_failure({
        failed: 8,
        total: 8,
        names: "Item f0, Item f1, Item f2, Item f3, Item f4, …"
      })
    );
  });
});

describe("SharePointWrapperActions while a sync is active", () => {
  it("offers no second resync of the folders", async () => {
    api.triggerFullSync.mockReset();
    render(SharePointWrapperActions, {
      wrapperId: "w-1",
      wrapperName: "Intranet",
      itemCount: items.length,
      items,
      canEdit: true,
      canDelete: true,
      syncActive: true
    });

    await page.getByRole("button", { name: m.actions() }).click();
    await expect
      .element(page.getByRole("menuitem", { name: m.integration_sync_already_running() }))
      .toHaveAttribute("aria-disabled", "true");
    expect(page.getByRole("menuitem", { name: m.resync_all_wrapper() }).elements()).toHaveLength(0);

    // Reachable with the arrow keys, so the reason is heard, and choosing it does nothing.
    const reason = page.getByRole("menuitem", { name: m.integration_sync_already_running() });
    for (let step = 0; step < 3 && document.activeElement !== reason.element(); step++) {
      await userEvent.keyboard("{ArrowDown}");
    }
    expect(document.activeElement).toBe(reason.element());
    await userEvent.keyboard("{Enter}");
    expect(page.getByRole("alertdialog").elements()).toHaveLength(0);
    expect(api.triggerFullSync).not.toHaveBeenCalled();
  });
});
