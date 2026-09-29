// Runs inside sandbox children only: reads CSV or XLSX files a spreadsheet takes its sheets
// from. DuckDB types the columns, so numbers stay numbers in the rendered workbook.
import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { DuckDBInstance } from "@duckdb/node-api";
import { ToolError } from "../../errors";
import { convertXlsxToCsvSheets } from "../tabular/engine/xlsx-to-csv";
import { assertZipWithinBounds } from "../tabular/zip-guard";
import type {
  Cell,
  DocumentRequest,
  DocumentSpec,
  SheetRequest,
  SheetSource,
  SheetSpec,
} from "./ports";

/** Rows one source sheet may contribute; Excel itself stops at 1,048,576. */
export const SOURCE_ROW_LIMIT = 200_000;
const MAX_EXPANDED_BYTES = 64 * 1024 * 1024;

export async function resolveSources(document: DocumentRequest): Promise<DocumentSpec> {
  if (document.kind !== "sheets") return document;
  const sheets: SheetSpec[] = [];
  for (const sheet of document.sheets) sheets.push(await resolveSheet(sheet));
  return { kind: "sheets", title: document.title, sheets };
}

async function resolveSheet(sheet: SheetRequest): Promise<SheetSpec> {
  if (!sheet.source)
    return { name: sheet.name, columns: sheet.columns ?? [], rows: sheet.rows ?? [] };
  const { columns, rows } = await readSource(sheet.source);
  return { name: sheet.name, columns, rows };
}

/** Reads a downloaded CSV or XLSX source (one sheet) as typed columns and rows. */
export async function readSource(
  source: SheetSource,
): Promise<{ columns: string[]; rows: Cell[][] }> {
  const { path, isXlsx } = source;
  if (!path) throw new ToolError("RENDER_FAILED", "A source file was not downloaded.");
  const bytes = await readFile(path);
  let csvPath = path;
  if (isXlsx) {
    if (bytes.length < 2 || bytes.readUInt16LE(0) !== 0x4b50)
      throw new ToolError("INVALID_FILE", "The source is not an XLSX workbook.");
    assertZipWithinBounds(bytes, MAX_EXPANDED_BYTES);
    const workbook = await convertXlsxToCsvSheets(bytes);
    const wanted = source.sheet;
    if (!wanted && workbook.length > 1)
      throw new ToolError(
        "SHEET_REQUIRED",
        `The source workbook has several sheets (${workbook.map((s) => s.name).join(", ")}). Pass source.sheet.`,
      );
    const picked = wanted ? workbook.find((s) => s.name === wanted) : workbook[0];
    if (!picked) throw new ToolError("UNKNOWN_SHEET", "Unknown sheet in the source workbook.");
    csvPath = join(dirname(path), `${source.index}.csv`);
    await writeFile(csvPath, picked.csv, { mode: 0o600 });
  } else {
    if (bytes.includes(0))
      throw new ToolError("INVALID_FILE", "The source is not a text CSV file.");
    try {
      new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      throw new ToolError("INVALID_FILE", "CSV sources must use UTF-8 encoding.");
    }
  }
  return readTypedCsv(csvPath);
}

async function readTypedCsv(csvPath: string): Promise<{ columns: string[]; rows: Cell[][] }> {
  // Server-built SQL over a file this child was given; no model SQL runs here.
  const instance = await DuckDBInstance.create(":memory:", {
    memory_limit: "256MB",
    threads: "1",
    allow_community_extensions: "false",
    autoinstall_known_extensions: "false",
    autoload_known_extensions: "false",
  });
  try {
    const conn = await instance.connect();
    try {
      const literal = "'" + csvPath.replaceAll("'", "''") + "'";
      const reader = await conn.runAndReadAll(
        `SELECT * FROM read_csv_auto(${literal}) LIMIT ${SOURCE_ROW_LIMIT + 1}`,
      );
      const rows = reader.getRowsJS();
      if (rows.length > SOURCE_ROW_LIMIT)
        throw new ToolError(
          "SOURCE_TOO_LARGE",
          `The source has more than ${SOURCE_ROW_LIMIT} rows. Filter or aggregate it first with query_table.`,
        );
      return { columns: reader.columnNames(), rows: rows.map((row) => row.map(toCell)) };
    } finally {
      conn.closeSync();
    }
  } catch (error) {
    if (error instanceof ToolError) throw error;
    throw new ToolError("INVALID_FILE", "The source could not be read as a table.");
  } finally {
    instance.closeSync();
  }
}

function toCell(value: unknown): Cell {
  if (value === null || value === undefined) return null;
  if (typeof value === "bigint")
    return value <= BigInt(Number.MAX_SAFE_INTEGER) && value >= BigInt(Number.MIN_SAFE_INTEGER)
      ? Number(value)
      : value.toString();
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "string")
    return value;
  // Dates, timestamps and decimals keep DuckDB's own text form.
  return String(value);
}
