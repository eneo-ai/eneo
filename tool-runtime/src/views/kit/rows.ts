// What a view does with the rows it holds, whatever tool they came from.

/** Rows ordered by one column, as a view sorts what it already holds. */
export function sortRows(rows: unknown[][], index: number, descending: boolean): unknown[][] {
  const direction = descending ? -1 : 1;
  return [...rows].sort((left, right) => {
    const a = left[index];
    const b = right[index];
    // Missing values last, in either direction, as SQL orders them.
    if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1;
    if (b === null || b === undefined) return -1;
    if (typeof a === "number" && typeof b === "number") return (a - b) * direction;
    return String(a).localeCompare(String(b), undefined, { numeric: true }) * direction;
  });
}

/** The rows in which some cell contains `text`, ignoring case. */
export function filterRows(rows: unknown[][], text: string): unknown[][] {
  const needle = text.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((row) =>
    row.some(
      (cell) => cell !== null && cell !== undefined && String(cell).toLowerCase().includes(needle),
    ),
  );
}

/** Rows as tab-separated text with a header line, for pasting into a spreadsheet. */
export function toTsv(columns: string[], rows: unknown[][]): string {
  const cell = (value: unknown) =>
    value === null || value === undefined ? "" : String(value).replace(/[\t\r\n]+/g, " ");
  return [columns, ...rows].map((row) => row.map(cell).join("\t")).join("\n");
}
