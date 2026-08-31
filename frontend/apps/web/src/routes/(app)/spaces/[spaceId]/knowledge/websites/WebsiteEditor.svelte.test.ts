import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const createWebsite = vi.hoisted(() => vi.fn());
const updateWebsite = vi.hoisted(() => vi.fn());
const checkUrl = vi.hoisted(() => vi.fn());
const refreshCurrentSpace = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    websites: {
      create: createWebsite,
      update: updateWebsite,
      checkUrl
    }
  })
}));

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    refreshCurrentSpace,
    state: {
      currentSpace: {
        subscribe: (run: (space: unknown) => void) => {
          run({
            id: "space-1",
            organization: false,
            embedding_models: [
              {
                id: "model-1",
                name: "Embedding model",
                open_source: false,
                stability: "stable"
              }
            ]
          });
          return () => {};
        }
      }
    }
  })
}));

import WebsiteEditor from "./WebsiteEditor.svelte";

describe("WebsiteEditor", () => {
  beforeEach(() => {
    createWebsite.mockReset().mockResolvedValue({});
    updateWebsite.mockReset().mockResolvedValue({});
    checkUrl.mockReset().mockResolvedValue(null);
    refreshCurrentSpace.mockReset();
  });

  it("keeps the dialog actions clear of the bottom edge", async () => {
    render(WebsiteEditor, { mode: "create" });

    await page.getByRole("button", { name: m.connect_website(), exact: true }).click();

    const footer = document.querySelector<HTMLElement>('[data-slot="dialog-footer"]');
    expect(footer).not.toBeNull();
    expect(footer!.classList).toContain("mb-0");
    expect(footer!.classList).not.toContain("-mb-4");
    expect(footer!.classList).toContain("py-4");
  });

  it("submits a valid website with the keyboard", async () => {
    render(WebsiteEditor, { mode: "create" });

    await page.getByRole("button", { name: m.connect_website(), exact: true }).click();
    const dialog = page.getByRole("dialog");
    const url = dialog.getByRole("textbox", { name: m.url_required(), exact: true });
    await url.fill("https://sundsvall.se/kommun");
    await userEvent.keyboard("{Enter}");

    await vi.waitFor(() => expect(createWebsite).toHaveBeenCalledOnce());
  });

  it("preserves create form values and re-enables submission after a failure", async () => {
    createWebsite.mockRejectedValueOnce(new Error("temporary failure")).mockResolvedValueOnce({});
    render(WebsiteEditor, { mode: "create" });

    await page.getByRole("button", { name: m.connect_website(), exact: true }).click();
    const dialog = page.getByRole("dialog");
    const url = dialog.getByRole("textbox", { name: m.url_required(), exact: true });
    await url.fill("https://sundsvall.se/omsorg");

    const submit = dialog.getByRole("button", { name: m.create_website(), exact: true });
    await submit.click();
    await expect.element(dialog.getByText(m.website_form_create_failed())).toBeVisible();
    await expect.element(url).toHaveValue("https://sundsvall.se/omsorg");
    await expect.element(submit).toBeEnabled();

    await submit.click();
    await vi.waitFor(() => expect(createWebsite).toHaveBeenCalledTimes(2));
    expect(createWebsite.mock.calls[1]?.[0]).toMatchObject({
      url: "https://sundsvall.se/omsorg"
    });
  });

  it("retries an update with the same edits after a failed request", async () => {
    updateWebsite.mockRejectedValueOnce(new Error("temporary failure")).mockResolvedValueOnce({});
    render(WebsiteEditor, {
      mode: "update",
      showDialog: true,
      website: {
        id: "website-1",
        name: "Old name",
        url: "https://sundsvall.se/kommun",
        crawl_type: "crawl",
        download_files: false,
        update_interval: "never",
        requires_http_auth: false,
        embedding_model: { id: "model-1" }
      } as never
    });

    const dialog = page.getByRole("dialog");
    const name = dialog.getByRole("textbox", { name: m.display_name(), exact: true });
    await name.fill("Omsorg");
    await expect.element(name).toHaveValue("Omsorg");
    const submit = dialog.getByRole("button", { name: m.save_changes(), exact: true });

    await submit.click();
    await expect.element(dialog.getByText(m.website_form_update_failed())).toBeVisible();
    await expect.element(name).toHaveValue("Omsorg");
    await expect.element(submit).toBeEnabled();

    await submit.click();
    await vi.waitFor(() => expect(updateWebsite).toHaveBeenCalledTimes(2));
    expect(updateWebsite.mock.calls[1]?.[0]).toMatchObject({
      website: { id: "website-1" },
      update: { name: "Omsorg" }
    });
  });
});
