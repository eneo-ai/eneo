import { z } from "zod";
import { ToolError } from "../../errors";

/** Original preview coordinates: header is row 1; CSV counts records, not lines. */
export const sourceRows = z
  .array(z.number().int().min(2).max(1_048_576))
  .min(1)
  .max(500)
  .optional()
  .describe(
    "Exact source row numbers selected in the native file preview (header is row 1). Pass unchanged from the user's selection. Filters the source before SQL, aggregation, sorting or LIMIT; never infer row numbers from query results. CSV numbers count nonblank records, including quoted multiline records.",
  );
export type SourceSelection = { sheet?: string; source_rows: number[] };

export function selectCsvRows(bytes: Buffer, selection: SourceSelection): Buffer {
  if (selection.sheet && selection.sheet !== "Sheet1")
    throw new ToolError("UNKNOWN_SHEET", "CSV has only Sheet1.");
  const rows = parseDelimited(bytes.toString("utf8").replace(/^\uFEFF/, ""));
  if (!rows.length || selection.source_rows.some((row) => row > rows.length))
    throw new ToolError(
      "INVALID_SELECTION",
      "A selected source row is outside the file. Reopen the original file and select again.",
    );
  const width = Math.max(
    ...[rows[0]!, ...selection.source_rows.map((row) => rows[row - 1]!)].map((row) => row.length),
  );
  if (width > 200)
    throw new ToolError("INVALID_SELECTION", "The selection has too many columns (maximum 200).");
  const field = (text: string) => '"' + text.replaceAll('"', '""') + '"';
  return Buffer.from(
    [rows[0]!, ...selection.source_rows.map((row) => rows[row - 1]!)]
      .map((row) =>
        Array.from({ length: width }, (_, column) => field(row[column] ?? "")).join(","),
      )
      .join("\r\n") + "\r\n",
  );
}

const CANDIDATE_DELIMITERS = [",", ";", "\t"] as const;

/**
 * The delimiter of a CSV file, read from its first record: the candidate that
 * separates the most fields outside quotes. Spreadsheets in Swedish locales
 * export semicolons, so the comma cannot be assumed.
 */
export function sniffDelimiter(text: string): string {
  const counts = new Map<string, number>(CANDIDATE_DELIMITERS.map((d) => [d, 0]));
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i]!;
    if (char === '"') quoted = !quoted;
    else if (!quoted && (char === "\n" || char === "\r")) break;
    else if (!quoted && counts.has(char)) counts.set(char, counts.get(char)! + 1);
  }
  let best: string = ",";
  for (const delimiter of CANDIDATE_DELIMITERS) {
    if (counts.get(delimiter)! > counts.get(best)!) best = delimiter;
  }
  return best;
}

/**
 * Parses delimiter-separated text (RFC 4180 quoting: quoted fields may hold the
 * delimiter, line breaks and doubled quotes). Blank lines are skipped.
 */
export function parseDelimited(text: string, delimiter = sniffDelimiter(text)): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  // A field that opened with a quote stays a field even when empty ("").
  let wasQuoted = false;

  const endRow = () => {
    if (row.length > 0 || field !== "" || wasQuoted) {
      row.push(field);
      rows.push(row);
    }
    row = [];
    field = "";
    wasQuoted = false;
  };

  for (let i = 0; i < text.length; i++) {
    const char = text[i]!;
    if (quoted) {
      if (char !== '"') field += char;
      else if (text[i + 1] === '"') {
        field += '"';
        i++;
      } else quoted = false;
    } else if (char === '"' && field === "") {
      quoted = true;
      wasQuoted = true;
    } else if (char === delimiter) {
      row.push(field);
      field = "";
      wasQuoted = false;
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      endRow();
    } else field += char;
  }
  if (quoted)
    throw new ToolError("INVALID_SELECTION", "The CSV contains an unfinished quoted field.");
  endRow();
  return rows;
}
