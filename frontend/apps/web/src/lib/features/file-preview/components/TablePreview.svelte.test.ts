import { page, userEvent } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { afterEach, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import TablePreview from "./TablePreview.svelte";
import { parseTableLocator, tableLocator } from "../tableReference";
import { findPassage } from "../selection";

const sheets = [
  {
    name: "Data",
    rows: [
      ["Department", "Budget"],
      ["School", 21425],
      ["Care", null]
    ],
    totalRows: 3
  },
  {
    name: "Other",
    rows: [
      ["Department", "Budget"],
      ["Other school", 3]
    ],
    totalRows: 2
  }
];
const cell = (address: string, heading: string, value: string) =>
  page.getByRole("button", {
    name: m.table_reference_select_cell({ cell: address, heading, value }),
    exact: true
  });
afterEach(() => window.getSelection()?.removeAllRanges());

it("selects a cell without sending or quoting until the explicit action, and retains highlighting", async () => {
  const onquote = vi.fn();
  render(TablePreview, { sheets, onquote });
  const budget = cell("B2", "Budget", "21425");
  await budget.click();
  expect(onquote).not.toHaveBeenCalled();
  await expect.element(budget).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: m.table_reference_ask() }).click();
  expect(onquote).toHaveBeenCalledOnce();
  expect(onquote.mock.calls[0][0]).toContain("B · Budget: 21425");
  expect(onquote.mock.calls[0][0]).toContain("A · Department: School");
  expect(parseTableLocator(onquote.mock.calls[0][1])).toEqual({ sheet: "Data", row: 2, column: 1 });
  await expect.element(budget).toHaveAttribute("aria-pressed", "true");
});
it("quotes a row reference without copying cell values", async () => {
  const onquote = vi.fn();
  render(TablePreview, { sheets, onquote });
  await page
    .getByRole("button", { name: m.table_reference_select_row({ row: 3 }), exact: true })
    .click();
  await page.getByRole("button", { name: m.table_reference_ask() }).click();
  expect(onquote.mock.calls[0][0]).toBe(m.table_reference_rows_selected({ count: 1 }));
  expect(parseTableLocator(onquote.mock.calls[0][1])?.rows).toEqual([3]);
  expect(parseTableLocator(onquote.mock.calls[0][1])?.column).toBeNull();
});
it("supports one table tab stop, arrow navigation, keyboard selection and Escape", async () => {
  render(TablePreview, { sheets, onquote: vi.fn() });
  const first = cell("A2", "Department", "School");
  (first.element() as HTMLElement).focus();
  await userEvent.keyboard("{ArrowRight}{Enter}");
  await expect.element(cell("B2", "Budget", "21425")).toHaveAttribute("aria-pressed", "true");
  expect(document.querySelectorAll("table button[tabindex='0']")).toHaveLength(1);
  await userEvent.keyboard("{Home}{Enter}");
  await expect
    .element(
      page.getByRole("button", { name: m.table_reference_select_row({ row: 2 }), exact: true })
    )
    .toHaveAttribute("aria-pressed", "true");
  await userEvent.keyboard("{Escape}");
  expect(page.getByRole("button", { name: m.table_reference_ask() }).elements()).toHaveLength(0);
});
it("clears temporary selection when changing sheets", async () => {
  render(TablePreview, { sheets, onquote: vi.fn() });
  await cell("B2", "Budget", "21425").click();
  await page.getByRole("tab", { name: "Other", exact: true }).click();
  expect(page.getByRole("button", { name: m.table_reference_ask() }).elements()).toHaveLength(0);
  await expect.element(cell("A2", "Department", "Other school")).toBeVisible();
});
it("reopens a saved location by coordinates even when the excerpt is labelled or shortened", async () => {
  const locator = tableLocator({ sheet: "Other", row: 2, column: 1 });
  render(TablePreview, {
    sheets,
    sheet: "Other",
    highlight: { text: "Labelled excerpt", locator },
    onquote: vi.fn()
  });
  await expect.element(cell("B2", "Budget", "3")).toHaveAttribute("aria-pressed", "true");
  const range = findPassage(document.body, "not literal cell text", locator)[0];
  expect(range.toString()).toBe("3");
});
it("does not replace ordinary drag-to-select text with a cell selection", async () => {
  const onquote = vi.fn();
  render(TablePreview, { sheets, onquote });
  const button = cell("A2", "Department", "School").element();
  const range = document.createRange();
  range.selectNodeContents(button);
  window.getSelection()?.addRange(range);
  (button as HTMLButtonElement).click();
  expect(window.getSelection()?.toString()).toBe("School");
  expect(page.getByRole("button", { name: m.table_reference_ask() }).elements()).toHaveLength(0);
  expect(onquote).not.toHaveBeenCalled();
});
it("reports references beyond the preview without offering a misleading selection", async () => {
  render(TablePreview, {
    sheets,
    highlight: { text: "outside", locator: tableLocator({ sheet: "Data", row: 900, column: 0 }) },
    onquote: vi.fn()
  });
  await expect.element(page.getByText(m.table_reference_location_unavailable())).toBeVisible();
  expect(page.getByRole("button", { name: m.table_reference_ask() }).elements()).toHaveLength(0);
});

it("toggles multiple rows and restores every selected row without copying values", async () => {
  const onquote = vi.fn();
  render(TablePreview, { sheets, onquote });
  const row = (number: number) =>
    page.getByRole("button", { name: m.table_reference_select_row({ row: number }), exact: true });
  await row(2).click();
  await row(3).click();
  await page.getByRole("button", { name: m.table_reference_ask() }).click();
  const [text, locator] = onquote.mock.calls[0];
  expect(text).toBe(m.table_reference_rows_selected({ count: 2 }));
  expect(text).not.toContain("21425");
  expect(parseTableLocator(locator)?.rows).toEqual([2, 3]);
  expect(findPassage(document.body, text, locator)).toHaveLength(2);
  await row(2).click();
  await expect.element(row(2)).toHaveAttribute("aria-pressed", "false");
  await expect.element(row(3)).toHaveAttribute("aria-pressed", "true");
});
it("extends a row range with Shift and arrow keys", async () => {
  const onquote = vi.fn();
  render(TablePreview, { sheets, onquote });
  const row = page.getByRole("button", {
    name: m.table_reference_select_row({ row: 2 }),
    exact: true
  });
  await row.click();
  await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");
  await page.getByRole("button", { name: m.table_reference_ask() }).click();
  expect(parseTableLocator(onquote.mock.calls[0][1])?.rows).toEqual([2, 3]);
});
