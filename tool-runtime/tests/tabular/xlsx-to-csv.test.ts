/**
 * The XLSX → per-sheet CSV converter, with the sheet-name edge cases Excel
 * itself never produces but other exporters do: names over 31 characters,
 * and names that collide once truncated. ExcelJS throws "Worksheet name
 * already exists" on the former (it truncates, re-applies the parsed name,
 * and finds the worksheet itself), which took down every workbook from one
 * municipal energy export.
 */
import ExcelJS from "exceljs";
import JSZip from "jszip";
import { describe, expect, it } from "bun:test";

import { convertXlsxToCsvSheets } from "../../src/tools/tabular/engine/xlsx-to-csv";

/** Build a workbook with ExcelJS, then rename its sheets in the XML to names ExcelJS refuses to author. */
async function workbookWithSheetNames(names: string[]): Promise<Buffer> {
  const wb = new ExcelJS.Workbook();
  names.forEach((_, i) => {
    const ws = wb.addWorksheet(`S${i + 1}`);
    ws.addRow(["id", "value"]);
    ws.addRow([i + 1, `row of sheet ${i + 1}`]);
  });
  const built = Buffer.from(await wb.xlsx.writeBuffer());
  const zip = await JSZip.loadAsync(built);
  let xml = await zip.file("xl/workbook.xml")!.async("string");
  names.forEach((name, i) => {
    xml = xml.replace(
      `name="S${i + 1}"`,
      `name="${name.replace(/&/g, "&amp;")}"`,
    );
  });
  zip.file("xl/workbook.xml", xml);
  return zip.generateAsync({ type: "nodebuffer" });
}

describe("convertXlsxToCsvSheets", () => {
  it("converts a workbook whose sheet name exceeds Excel's 31-character limit", async () => {
    const long = "Periodiserade Månadsförbrukningar"; // 33 chars, straight from the failing export
    const bytes = await workbookWithSheetNames([
      "Värden",
      long,
      "Periodenergi",
    ]);

    const sheets = await convertXlsxToCsvSheets(bytes);

    expect(sheets.map((s) => s.name)).toEqual(["Värden", long, "Periodenergi"]);
    expect(sheets[1]!.csv.toString("utf8")).toContain("row of sheet 2");
  });

  it("keeps sheets apart when their names collide after truncation", async () => {
    const a = "Periodiserade Månadsförbrukningar 2024";
    const b = "Periodiserade Månadsförbrukningar 2025";
    const bytes = await workbookWithSheetNames([a, b]);

    const sheets = await convertXlsxToCsvSheets(bytes);

    expect(sheets.map((s) => s.name)).toEqual([a, b]);
    expect(sheets[0]!.csv.toString("utf8")).toContain("row of sheet 1");
    expect(sheets[1]!.csv.toString("utf8")).toContain("row of sheet 2");
  });

  it("passes a well-formed workbook through untouched, entities included", async () => {
    const bytes = await workbookWithSheetNames(["Intäkter & kostnader", "Q1"]);

    const sheets = await convertXlsxToCsvSheets(bytes);

    expect(sheets.map((s) => s.name)).toEqual(["Intäkter & kostnader", "Q1"]);
  });

  it("writes every row at one width — a stray header cell no longer makes DuckDB drop the data", async () => {
    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet("Värden");
    ws.addRow(["Starttid", "Värde", "Status", " "]); // the exporter's whitespace cell in D1
    ws.addRow([new Date(Date.UTC(2026, 0, 1)), 0.964, "Normalt"]);
    ws.addRow([]); // blank rows are skipped, not emitted as ",,"
    ws.addRow([
      new Date(Date.UTC(2026, 0, 1, 0, 15)),
      0.772,
      'Normalt, "kontrollerad"',
    ]);
    const bytes = Buffer.from(await wb.xlsx.writeBuffer());

    const [sheet] = await convertXlsxToCsvSheets(bytes);
    const lines = sheet!.csv.toString("utf8").trimEnd().split("\n");

    expect(lines).toEqual([
      "Starttid,Värde,Status",
      "2026-01-01,0.964,Normalt", // a date without a time of day is written as a date
      '2026-01-01T00:15:00.000Z,0.772,"Normalt, ""kontrollerad"""',
    ]);
  });

  it("skips a sheet that holds only blanks", async () => {
    const wb = new ExcelJS.Workbook();
    wb.addWorksheet("Tom").addRow([" ", ""]);
    const data = wb.addWorksheet("Data");
    data.addRow(["a"]);
    data.addRow([1]);
    const bytes = Buffer.from(await wb.xlsx.writeBuffer());

    const sheets = await convertXlsxToCsvSheets(bytes);
    expect(sheets.map((s) => s.name)).toEqual(["Data"]);
  });
});

it("reports ordinary/shared formulas and distinguishes missing results from zero, false and empty text", async () => {
  const book = new ExcelJS.Workbook();
  const sheet = book.addWorksheet("Calculations");
  sheet.addRow(["id", "value"]);
  sheet.addRow([1, { formula: "1-1", result: 0 }]);
  sheet.addRow([2, { formula: "1=2", result: false }]);
  sheet.addRow([3, { formula: '""', result: "" }]);
  sheet.addRow([4, { formula: "2+2" }]);
  sheet.addRow([5, { sharedFormula: "B2", result: 3 }]);
  book.addWorksheet("No results").getCell("A1").value = { formula: "1+1" };
  const bytes = Buffer.from(await book.xlsx.writeBuffer());
  const sheets = await convertXlsxToCsvSheets(bytes);
  expect(sheets[0]!.calculation).toEqual({
    formula_cells: 5,
    missing_cached_results: 1,
    recalculated: false,
  });
  expect(sheets[0]!.csv.toString()).toContain("1,0");
  expect(sheets[0]!.csv.toString()).toContain("2,false");
  expect(sheets[1]!.calculation?.missing_cached_results).toBe(1);
  expect(sheets[1]!.csv.length).toBe(0);
});
