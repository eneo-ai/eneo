// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { PreviewSheet } from "./load-preview";
import { findPassage, locatePassage } from "./selection";
import { parseTableLocator, tableLocator } from "./table-reference";
import { TablePreview } from "./table-preview";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(() => {
  cleanup();
  window.getSelection()?.removeAllRanges();
});

const sheets: PreviewSheet[] = [
  {
    name: "Data",
    rows: [
      ["Department", "Budget", "Start"],
      ["School", 21425.5, new Date(Date.UTC(2026, 0, 31))],
      ["Care", null, null],
      ["Culture", 2026, null]
    ],
    totalRows: 4
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

const ask = () => screen.queryByRole("button", { name: "Fråga om markeringen" });
const row = (number: number) => screen.getByRole("checkbox", { name: `Markera rad ${number}` });

function renderTable(props: Partial<Parameters<typeof TablePreview>[0]> = {}) {
  const onQuote = vi.fn();
  renderInApp(<TablePreview sheets={sheets} title="budget.xlsx" onQuote={onQuote} {...props} />);
  return onQuote;
}

it("quotes selected rows as a row reference, without their values", () => {
  const onQuote = renderTable();
  expect(ask()).toBeNull();
  fireEvent.click(row(3));
  fireEvent.click(row(2));
  fireEvent.click(ask()!);

  expect(onQuote).toHaveBeenCalledOnce();
  const [text, locator] = onQuote.mock.calls[0]!;
  expect(text).toBe("Markerade rader: 2");
  expect(locator).toBe(tableLocator({ sheet: "Data", row: 2, column: null, rows: [2, 3] }));
  expect(screen.getByText("Data · Markerade rader: 2")).toBeTruthy();
});

it("extends from the last row picked with Shift, and Escape drops the selection", () => {
  const onQuote = renderTable();
  fireEvent.click(row(2));
  fireEvent.click(row(4), { shiftKey: true });
  fireEvent.click(ask()!);
  expect(parseTableLocator(onQuote.mock.calls[0]![1])?.rows).toEqual([2, 3, 4]);

  const checkbox = row(3);
  checkbox.focus();
  expect(document.activeElement).toBe(checkbox);
  fireEvent.keyDown(checkbox, { key: "Escape" });
  expect(ask()).toBeNull();
  expect((row(3) as HTMLInputElement).checked).toBe(false);
});

it("formats numbers without grouping and dates as UTC days", () => {
  renderTable();
  expect(screen.getByText("21425,5")).toBeTruthy();
  expect(screen.getByText("2026")).toBeTruthy();
  expect(screen.getByText("2026-01-31")).toBeTruthy();
});

it("anchors rows and cells so a text selection and a quote find their place", () => {
  renderTable();
  const table = screen.getByRole("table", { name: "Data" });
  expect(table.dataset.sheet).toBe("Data");
  const cell = within(table).getByText("Care").closest("td")!;
  expect(cell.dataset.column).toBe("0");
  expect(cell.closest("tr")?.dataset.row).toBe("3");
  // The row number and the checkbox are chrome a selection never takes in.
  expect(cell.closest("tr")?.querySelectorAll(":scope > .select-none")).toHaveLength(2);

  const range = document.createRange();
  range.selectNodeContents(cell);
  expect(locatePassage(document.body, range, "Care")).toBe(
    'sheet "Data", row 3 (data row 2), cells: Care |  | '
  );
  const budget = findPassage(
    document.body,
    "not literal cell text",
    tableLocator({ sheet: "Data", row: 2, column: 1 })
  );
  expect(budget.map(String)).toEqual(["21425,5"]);
});

it("brings a passage's sheet forward and selects its rows", () => {
  const locator = tableLocator({ sheet: "Other", row: 2, column: null });
  renderTable({ sheet: "Other", highlight: { text: "Markerade rader: 1", locator } });
  expect(screen.getByRole("tab", { name: "Other" }).getAttribute("aria-selected")).toBe("true");
  expect((row(2) as HTMLInputElement).checked).toBe(true);
  expect(screen.getByText("Other school")).toBeTruthy();
});

it("says so when a passage lies beyond the preview, and selects nothing", () => {
  renderTable({
    highlight: { text: "outside", locator: tableLocator({ sheet: "Data", row: 900, column: 0 }) }
  });
  expect(
    screen.getByText("Markeringen ligger utanför den tillgängliga förhandsvisningen.")
  ).toBeTruthy();
  expect(ask()).toBeNull();
});

it("clears the selection when another sheet is shown", () => {
  renderTable();
  fireEvent.click(row(2));
  act(() => screen.getByRole("tab", { name: "Other" }).click());
  expect(ask()).toBeNull();
  expect(screen.getByText("Other school")).toBeTruthy();
});

it("has no axe violations with rows selected", async () => {
  renderTable();
  fireEvent.click(row(2));
  await expectNoAxeViolations(document.body);
});
