import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const api = vi.hoisted(() => ({
  triggerFullSync: vi.fn(),
  refreshCurrentSpace: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn()
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

import SharePointWrapperActions from "./SharePointWrapperActions.svelte";

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
    api.triggerFullSync.mockResolvedValue(undefined);
    await openResyncDialog();
    await confirmResync();

    expect(api.triggerFullSync).toHaveBeenCalledTimes(items.length);
    expect(api.toastSuccess).toHaveBeenCalledWith(
      m.resync_all_wrapper_queued({ count: items.length })
    );
    expect(api.toastError).not.toHaveBeenCalled();
  });

  it("names the failed count, closes the dialog and only re-queues on a new confirm", async () => {
    api.triggerFullSync.mockImplementation(({ knowledge }: { knowledge: IntegrationKnowledge }) =>
      knowledge.id === "b" || knowledge.id === "d"
        ? Promise.reject(new Error("boom"))
        : Promise.resolve(undefined)
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

    await openResyncDialog();
    expect(api.triggerFullSync).toHaveBeenCalledTimes(items.length);

    await confirmResync();
    expect(api.triggerFullSync).toHaveBeenCalledTimes(items.length * 2);
  });
});
