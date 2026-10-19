import { expect, it } from "vitest";
import {
  columnName,
  tableExcerpt,
  tableLocator,
  parseTableLocator,
  toggleTableRows,
  tableLocationLabel
} from "./tableReference";
import { isLocator, locatorSheet } from "./selection";

const sheet = {
  name: 'Utfall "2025", juli',
  rows: [
    ["Förvaltning", "Månad", "Budget", "Budget", ""],
    ["Skola", "Juli", 0, 21425, null]
  ],
  totalRows: 2
};
const labels = { empty: "(empty)", truncated: "… shortened" };
const format = (value: unknown) => (value == null ? "" : String(value));
it.each([
  [0, "A"],
  [25, "Z"],
  [26, "AA"],
  [701, "ZZ"],
  [702, "AAA"]
])("names column %i as %s", (index, name) => expect(columnName(index as number)).toBe(name));
it.each([null, 0, 27])("round trips a location with quoted sheet names and column %s", (column) => {
  const selection = { sheet: sheet.name, row: 2, column };
  const locator = tableLocator(selection);
  expect(parseTableLocator(locator)).toEqual(selection);
  expect(isLocator(locator)).toBe(true);
  expect(locatorSheet(locator)).toBe(sheet.name);
  expect(tableLocationLabel(locator, (row) => `Row ${row}`)).toContain(
    column === null ? "Row 2" : `${columnName(column)}2`
  );
});
it("rejects invalid or inconsistent coordinates", () => {
  for (const locator of [
    'sheet "a", row 0 (data row -1)',
    'sheet "a", row 2 (data row 2)',
    'sheet "a", row 2 (data row 1), column <script>',
    'sheet "a", row 99999999999999999 (data row 1)'
  ])
    expect(parseTableLocator(locator)).toBeNull();
});
it("includes the chosen cell first and enough labelled row context", () => {
  const text = tableExcerpt(sheet, { sheet: sheet.name, row: 2, column: 3 }, format, labels);
  expect(text.split("\n")[0]).toBe("D · Budget: 21425");
  expect(text).toContain("A · Förvaltning: Skola");
  expect(text).toContain("C · Budget: 0");
});
it("distinguishes duplicate and missing headings and empty cells in rows", () => {
  const text = tableExcerpt(sheet, { sheet: sheet.name, row: 2, column: null }, format, labels);
  expect(text).toContain("C · Budget: 0");
  expect(text).toContain("D · Budget: 21425");
  expect(text).toContain("E: (empty)");
});
it("bounds long excerpts and announces omitted data", () => {
  const long = { ...sheet, rows: [Array(30).fill("Header"), Array(30).fill("x".repeat(900))] };
  const text = tableExcerpt(long, { sheet: sheet.name, row: 2, column: null }, format, labels);
  expect(text.length).toBeLessThan(1500);
  expect(text).toContain(labels.truncated);
});
it("does not substitute data when a sheet, row or cell is unavailable", () => {
  for (const selection of [
    { sheet: "other", row: 2, column: 0 },
    { sheet: sheet.name, row: 3, column: null },
    { sheet: sheet.name, row: 2, column: 10 }
  ])
    expect(tableExcerpt(sheet, selection, format, labels)).toBe("");
});

it("round trips precise non-contiguous row references", () => {
  const selection = { sheet: sheet.name, row: 2, column: null, rows: [2, 4, 8] };
  const locator = tableLocator(selection);
  expect(parseTableLocator(locator)).toEqual(selection);
  expect(isLocator(locator)).toBe(true);
  expect(locatorSheet(locator)).toBe(sheet.name);
});
it("rejects malformed row selection references", () => {
  for (const rows of [
    "[]",
    "[0]",
    "[1]",
    "[2.5]",
    "[-2]",
    "[2000000]",
    JSON.stringify(Array(501).fill(2))
  ])
    expect(parseTableLocator(`sheet "Data", source rows ${rows}`)).toBeNull();
});
it("toggles disjoint rows and extends anchored ranges", () => {
  expect(toggleTableRows([2, 5], 2, 5, false)).toEqual([5]);
  expect(toggleTableRows([2], 6, 2, true)).toEqual([2, 3, 4, 5, 6]);
  expect(toggleTableRows([2, 7], 5, 7, true)).toEqual([2, 5, 6, 7]);
});
