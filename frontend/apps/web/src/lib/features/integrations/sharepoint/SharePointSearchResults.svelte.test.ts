import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { ComponentProps } from "svelte";
import { describe, expect, it, vi } from "vitest";
import * as m from "$lib/paraglide/messages";
import SharePointSearchResults from "./SharePointSearchResults.svelte";
import type { SharePointTreeItem } from "./treeState";

const hit: SharePointTreeItem = {
  id: "f1",
  name: "Rutin för larm.docx",
  type: "file",
  path: "/Rutiner/Larm/Rutin för larm.docx",
  has_children: false,
  size: 12_000,
  source_metadata: [{ name: "Dokumenttyp", label: "Dokumenttyp", value: "Rutin", kind: "choice" }]
};

function show(overrides: Partial<ComponentProps<typeof SharePointSearchResults>> = {}) {
  return render(SharePointSearchResults, {
    items: [hit],
    query: "rutin",
    loading: false,
    error: false,
    truncated: false,
    selectedItemKeySet: new Set<string>(),
    selectedPaths: [],
    onToggleSelect: vi.fn(),
    onRetry: vi.fn(),
    ...overrides
  });
}

describe("SharePointSearchResults", () => {
  it("shows each hit with its folder, properties and the matched text marked", async () => {
    show();

    await expect.element(page.getByText("Rutin för larm.docx")).toBeVisible();
    await expect.element(page.getByText("/Rutiner/Larm")).toBeVisible();
    await expect.element(page.getByText("Dokumenttyp:")).toBeVisible();
    expect([...document.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual([
      "Rutin",
      "Rutin"
    ]);
  });

  it("ticks a hit and reports it to the caller", async () => {
    const onToggleSelect = vi.fn();
    show({ onToggleSelect });

    await page
      .getByRole("checkbox", { name: m.sharepoint_select_item({ name: hit.name }) })
      .click();

    expect(onToggleSelect).toHaveBeenCalledWith(hit);
  });

  it("shows a hit under a selected folder as covered and not toggleable", async () => {
    show({ selectedPaths: ["/Rutiner"] });

    const box = page.getByRole("checkbox", { name: m.sharepoint_select_item({ name: hit.name }) });
    await expect.element(box).toBeChecked();
    await expect.element(box).toBeDisabled();
  });

  it("explains an empty result and a cut-off list", async () => {
    show({ items: [] });
    await expect.element(page.getByText(m.sharepoint_search_no_results())).toBeVisible();

    show({ truncated: true });
    await expect
      .element(page.getByText(m.sharepoint_search_truncated({ count: "1" })))
      .toBeVisible();
  });

  it("reports an incomplete search even when no files were found", async () => {
    show({ items: [], truncated: true });

    await expect.element(page.getByText(m.sharepoint_search_no_results())).toBeVisible();
    await expect
      .element(page.getByText(m.sharepoint_search_truncated({ count: "0" })))
      .toBeVisible();
  });
});
