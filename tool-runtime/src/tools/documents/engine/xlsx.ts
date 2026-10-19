import ExcelJS from "exceljs";
import type { DocumentSpec } from "../ports";

const INVALID_SHEET_CHARS = /[\\/?*[\]:]/g;
export function sheetName(raw: string, taken: Set<string>): string {
  const base =
    raw
      .replace(INVALID_SHEET_CHARS, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/^'+|'+$/g, "")
      .slice(0, 31) || "Blad";
  let name = base;
  for (let n = 2; taken.has(name.toLowerCase()); n++) {
    const suffix = ` (${n})`;
    name = `${base.slice(0, 31 - suffix.length)}${suffix}`;
  }
  taken.add(name.toLowerCase());
  return name;
}
export async function renderXlsx(
  document: Extract<DocumentSpec, { kind: "sheets" }>,
): Promise<Buffer> {
  const workbook = new ExcelJS.Workbook();
  workbook.title = document.title;
  const taken = new Set<string>();
  for (const sheet of document.sheets) {
    const worksheet = workbook.addWorksheet(sheetName(sheet.name, taken));
    const header = worksheet.addRow(sheet.columns);
    header.font = { bold: true };
    worksheet.views = [{ state: "frozen", ySplit: 1 }];
    for (const row of sheet.rows) {
      // Strings stay strings: a cell text beginning with "=" is never a formula here.
      worksheet.addRow(row.map((cell) => (cell === null ? null : cell)));
    }
    worksheet.columns.forEach((column, index) => {
      const values = [sheet.columns[index] ?? "", ...sheet.rows.map((r) => String(r[index] ?? ""))];
      column.width = Math.min(60, Math.max(10, ...values.map((v) => v.length + 2)));
    });
  }
  return Buffer.from(await workbook.xlsx.writeBuffer());
}
