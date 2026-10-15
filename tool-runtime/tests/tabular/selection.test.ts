import { expect, test } from "bun:test";
import { parseDelimited, selectCsvRows } from "../../src/tools/tabular/selection";

test("CSV coordinates count nonblank records, retain duplicates and quoted newlines", () => {
  const csv = Buffer.from('label;amount\r\n\r\n"line one\nline two";7\r\nsame;9\r\nsame;3\r\n');
  const selected = selectCsvRows(csv, { source_rows: [2, 4] });
  expect(parseDelimited(selected.toString())).toEqual([
    ["label", "amount"],
    ["line one\nline two", "7"],
    ["same", "3"],
  ]);
  expect(() => selectCsvRows(csv, { source_rows: [5] })).toThrow("outside");
});
test("TSV selection retains empty fields and pads short records", () => {
  expect(
    parseDelimited(
      selectCsvRows(Buffer.from("a\tb\n1\t\n2\t3\n"), { source_rows: [2] }).toString(),
    ),
  ).toEqual([
    ["a", "b"],
    ["1", ""],
  ]);
});
test("an unfinished quoted record is refused", () => {
  expect(() => selectCsvRows(Buffer.from('a,b\n"broken,4'), { source_rows: [2] })).toThrow(
    "unfinished",
  );
});
