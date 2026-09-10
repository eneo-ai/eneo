import { page } from "@vitest/browser/context";
import { readable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const bulkDelete = vi.hoisted(() => vi.fn());
const refreshCurrentSpace = vi.hoisted(() => vi.fn(async () => {}));
const toastInfo = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    websites: {
      bulkDelete,
      create: vi.fn(),
      update: vi.fn(),
      checkUrl: vi.fn()
    }
  })
}));

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    refreshCurrentSpace,
    state: {
      currentSpace: readable({
        id: "space-1",
        organization: false,
        embedding_models: []
      }),
      accessibleSpaces: readable([])
    }
  })
}));

vi.mock("$lib/components/toast", () => ({
  toast: {
    info: toastInfo,
    success: toastSuccess,
    error: vi.fn()
  }
}));

vi.mock("$lib/core/errors", () => ({ toastError }));

import WebsiteActions from "./WebsiteActions.svelte";

const WEBSITE_ID = "website-1";
const website = {
  id: WEBSITE_ID,
  name: "Sundsvall",
  url: "https://sundsvall.se/kommun",
  permissions: ["delete"],
  crawl_type: "crawl",
  download_files: false,
  update_interval: "never",
  requires_http_auth: false,
  embedding_model: null
};

async function confirmRemoval() {
  await page.getByRole("button", { name: m.actions(), exact: true }).click();
  await page.getByText(m.delete(), { exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect
    .element(dialog.getByText(m.remove_website_description(), { exact: true }))
    .toBeVisible();
  await dialog.getByRole("button", { name: m.remove_website_confirm(), exact: true }).click();
}

describe("WebsiteActions", () => {
  beforeEach(() => {
    bulkDelete.mockReset();
    refreshCurrentSpace.mockClear();
    toastInfo.mockClear();
    toastSuccess.mockClear();
    toastError.mockClear();
  });

  it("stops an active crawl and explains that removal must be retried", async () => {
    bulkDelete.mockResolvedValue({
      total: 1,
      deleted: 0,
      not_found: 0,
      failed: 1,
      errors: [{ website_id: website.id, error: "crawl_stop_requested" }]
    });
    render(WebsiteActions, { website: website as never });

    await confirmRemoval();

    expect(bulkDelete).toHaveBeenCalledWith({ website_ids: [website.id] });
    expect(toastInfo).toHaveBeenCalledWith(m.website_remove_stopping());
    expect(refreshCurrentSpace).toHaveBeenCalledWith("knowledge");
  });

  it("confirms a completed removal", async () => {
    bulkDelete.mockResolvedValue({
      total: 1,
      deleted: 1,
      not_found: 0,
      failed: 0,
      errors: []
    });
    render(WebsiteActions, { website: website as never });

    await confirmRemoval();

    expect(toastSuccess).toHaveBeenCalledWith(m.websites_removed({ count: 1 }));
  });
});
