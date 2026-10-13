import type { PreviewCell, PreviewSheet } from "./loadPreview";

/** Spreadsheet row numbers include the header; columns are zero-based. */
export type TableSelection = { sheet: string; row: number; column: number | null; rows?: number[] };

export function columnName(column: number): string {
  let name = "";
  for (let n = column + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  }
  return name;
}

export function tableLocator(selection: TableSelection): string {
  const { sheet, row, column } = selection;
  if (selection.rows)
    return `sheet ${JSON.stringify(sheet)}, source rows ${JSON.stringify(selection.rows)}`;
  return `sheet ${JSON.stringify(sheet)}, row ${row} (data row ${row - 1})${column === null ? "" : `, column ${columnName(column)}`}`;
}

const LOCATOR =
  /^sheet ("(?:[^"\\]|\\.)*"), row ([0-9]+) \(data row ([0-9]+)\)(?:, column ([A-Z]{1,5}))?$/;
export function parseTableLocator(locator: string | null | undefined): TableSelection | null {
  const multiple = locator
    ? /^sheet ("(?:[^"\\]|\\.)*"), source rows (\[[0-9,]+\])$/.exec(locator)
    : null;
  if (multiple) {
    try {
      const sheet: unknown = JSON.parse(multiple[1]);
      const rows: unknown = JSON.parse(multiple[2]);
      if (
        typeof sheet !== "string" ||
        !Array.isArray(rows) ||
        !rows.length ||
        rows.length > 500 ||
        !rows.every((row) => Number.isSafeInteger(row) && row >= 2 && row <= 1_048_576)
      )
        return null;
      const canonical = [...new Set<number>(rows)].sort((a, b) => a - b);
      return { sheet, row: canonical[0], column: null, rows: canonical };
    } catch {
      return null;
    }
  }
  const match = locator ? LOCATOR.exec(locator) : null;
  if (!match) return null;
  const row = Number(match[2]);
  if (!Number.isSafeInteger(row) || row < 2 || Number(match[3]) !== row - 1) return null;
  try {
    const sheet: unknown = JSON.parse(match[1]);
    if (typeof sheet !== "string") return null;
    const column = match[4]
      ? [...match[4]].reduce((n, letter) => n * 26 + letter.charCodeAt(0) - 64, 0) - 1
      : null;
    return { sheet, row, column };
  } catch {
    return null;
  }
}

/** Bounded, labelled context. A value is data, never an instruction or an access grant. */
export function tableExcerpt(
  sheet: PreviewSheet,
  selection: TableSelection,
  format: (value: PreviewCell | undefined) => string,
  labels: { empty: string; truncated: string }
): string {
  const row = sheet.rows[selection.row - 1];
  if (!row || sheet.name !== selection.sheet) return "";
  const header = sheet.rows[0] ?? [];
  const width = Math.max(header.length, row.length);
  if (selection.column !== null && (selection.column < 0 || selection.column >= width)) return "";
  let truncated = false;
  const clip = (text: string, max: number) => {
    const clean = text.replace(/\s+/g, " ").trim();
    if (clean.length <= max) return clean;
    truncated = true;
    return clean.slice(0, max) + "…";
  };
  const indices =
    selection.column === null
      ? Array.from({ length: width }, (_, index) => index)
      : [
          selection.column,
          ...Array.from({ length: Math.min(width, 4) }, (_, index) => index)
            .filter((index) => index !== selection.column)
            .slice(0, 3)
        ];
  const lines: string[] = [];
  let length = 0;
  for (const column of indices) {
    const heading = clip(format(header[column]), 80);
    const value = clip(format(row[column]), selection.column === column ? 500 : 180);
    const line = `${columnName(column)}${heading ? ` · ${heading}` : ""}: ${value || labels.empty}`;
    if (length + line.length > 1250) {
      truncated = true;
      break;
    }
    lines.push(line);
    length += line.length + 1;
  }
  if (truncated) lines.push(labels.truncated);
  return lines.join("\n");
}

/** Reader-facing location; never display the serialized file identity. */
export function tableLocationLabel(
  locator: string | null,
  rowLabel: (row: number) => string
): string | null {
  const selection = parseTableLocator(locator);
  if (!selection) return null;
  return [
    selection.sheet,
    selection.rows
      ? selection.rows.slice(0, 6).map(rowLabel).join(", ") + (selection.rows.length > 6 ? "…" : "")
      : selection.column === null
        ? rowLabel(selection.row)
        : `${columnName(selection.column)}${selection.row}`
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Toggle separate rows, or add a contiguous range from the last anchor. */
export function toggleTableRows(
  current: number[],
  row: number,
  anchor: number | null,
  extend: boolean
): number[] {
  if (extend && anchor !== null) {
    const range = Array.from(
      { length: Math.abs(row - anchor) + 1 },
      (_, i) => Math.min(row, anchor) + i
    );
    return [...new Set([...current, ...range])].sort((a, b) => a - b);
  }
  return current.includes(row)
    ? current.filter((value) => value !== row)
    : [...current, row].sort((a, b) => a - b);
}
