import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import * as m from "$lib/paraglide/messages";
import SharePointFilterChips from "./SharePointFilterChips.svelte";
import type { SharePointFilterColumn } from "./treeState";

const columns: SharePointFilterColumn[] = [
  { name: "Dokumenttyp", label: "Dokumenttyp", kind: "choice", choices: ["Rutin", "Policy"] },
  { name: "Extern", label: "Extern publicering", kind: "boolean", choices: [] }
];

describe("SharePointFilterChips", () => {
  it("shows chosen values as removable chips and reports the removal", async () => {
    const onChange = vi.fn();
    render(SharePointFilterChips, {
      columns,
      facets: { Dokumenttyp: "Policy", Extern: "true" },
      onChange
    });

    await expect.element(page.getByText("Policy")).toBeVisible();
    await expect.element(page.getByText(m.yes())).toBeVisible();

    await page
      .getByRole("button", { name: m.sharepoint_filter_remove({ column: "Extern publicering" }) })
      .click();

    expect(onChange).toHaveBeenCalledWith({ Dokumenttyp: "Policy" });
  });

  it("renders nothing without chosen filters", () => {
    render(SharePointFilterChips, { columns, facets: {}, onChange: vi.fn() });

    expect(page.getByRole("list").query()).toBeNull();
  });
});
