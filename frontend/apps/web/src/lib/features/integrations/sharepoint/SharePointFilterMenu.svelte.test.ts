import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import * as m from "$lib/paraglide/messages";
import SharePointFilterMenu from "./SharePointFilterMenu.svelte";
import type { SharePointFilterColumn } from "./treeState";

const columns: SharePointFilterColumn[] = [
  { name: "Dokumenttyp", label: "Dokumenttyp", kind: "choice", choices: ["Rutin", "Policy"] },
  { name: "Extern", label: "Extern publicering", kind: "boolean", choices: [] }
];

describe("SharePointFilterMenu", () => {
  it("shows chosen values as removable chips and reports changes", async () => {
    const onChange = vi.fn();
    render(SharePointFilterMenu, {
      columns,
      facets: { Dokumenttyp: "Policy", Extern: "true" },
      onChange
    });

    await expect
      .element(page.getByRole("button", { name: m.sharepoint_filters_aria({ count: "2" }) }))
      .toBeVisible();
    await expect.element(page.getByText("Policy")).toBeVisible();
    await expect.element(page.getByText(m.yes())).toBeVisible();

    await page
      .getByRole("button", { name: m.sharepoint_filter_remove({ column: "Extern publicering" }) })
      .click();

    expect(onChange).toHaveBeenCalledWith({ Dokumenttyp: "Policy" });
  });

  it("opens every column in one list instead of spreading them across the page", async () => {
    render(SharePointFilterMenu, { columns, facets: {}, onChange: vi.fn() });

    await page.getByRole("button", { name: m.sharepoint_filters_aria({ count: "0" }) }).click();

    await expect.element(page.getByText(m.sharepoint_filters_title())).toBeVisible();
    await expect.element(page.getByText("Dokumenttyp", { exact: true })).toBeVisible();
    await expect.element(page.getByText("Extern publicering", { exact: true })).toBeVisible();
  });

  it("renders nothing for a library without filterable columns", () => {
    render(SharePointFilterMenu, { columns: [], facets: {}, onChange: vi.fn() });

    expect(page.getByRole("button").query()).toBeNull();
  });
});
