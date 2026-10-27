import { selectCsvRows } from "./selection";
// Runs inside sandbox children only: parses untrusted workbooks and executes model-written SQL.
// The parent never imports this file, so neither ExcelJS nor native DuckDB loads in it.
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { ToolError } from "../../errors";
import { describeCsv, QueryRejectedError, runQuery } from "./engine/duckdb";
import { convertXlsxToCsvSheets } from "./engine/xlsx-to-csv";
import {
  convertJsonToCsvSheets,
  extractJsonPath,
  type JsonSummary,
} from "./engine/json-to-csv";
import { queryLimits } from "./config";
import type {
  IngestJob,
  IngestResult,
  JsonExtractJob,
  JsonExtractOutcome,
  QueryJob,
  QueryJobResult,
  SheetMetadata,
} from "./ports";
import { assertZipWithinBounds } from "./zip-guard";
import { toCsv } from "../files/csv";

const XLSX_TYPES = [
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/octet-stream",
];
const CSV_TYPES = [
  "text/tab-separated-values",
  "text/csv",
  "application/csv",
  "text/plain",
  "application/octet-stream",
];
const JSON_TYPES = [
  "application/json",
  "text/json",
  "application/x-ndjson",
  "application/jsonl",
  "application/x-jsonlines",
  "text/plain",
  "application/octet-stream",
];
const MAX_METADATA_BYTES = 256 * 1024;

/** Refuses bytes that are not UTF-8 text of the named kind. */
function assertUtf8Text(bytes: Buffer, kind: string): void {
  if (bytes.includes(0))
    throw new ToolError("INVALID_FILE", `The file is not a supported UTF-8 ${kind} file.`);
  try {
    new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new ToolError("INVALID_FILE", `${kind} files must use UTF-8 encoding.`);
  }
}

type IngestedSheet = import("./engine/xlsx-to-csv").SheetCsv & { jsonPath?: string };

/** The records of a JSON file as sheets; a selection narrows them to one sheet's rows. */
async function jsonSheets(
  job: IngestJob,
): Promise<{ sheets: IngestedSheet[]; json: JsonSummary }> {
  const { config } = job;
  const converted = await convertJsonToCsvSheets(job.inputPath, {
    maxSheets: config.max_sheets,
    maxExpandedBytes: config.max_expanded_bytes,
    memoryMb: config.memory_mb,
  });
  let sheets: IngestedSheet[] = converted.sheets.map((sheet) => ({
    name: sheet.name,
    csv: sheet.csv,
    jsonPath: sheet.json_path,
  }));
  if (job.selection) {
    const { sheet: requested, source_rows } = job.selection;
    if (!requested && sheets.length > 1)
      throw new ToolError("SHEET_REQUIRED", "The selection must name a sheet.");
    const sheet = requested ? sheets.find((s) => s.name === requested) : sheets[0];
    if (!sheet)
      throw new ToolError("UNKNOWN_SHEET", "Unknown sheet. Use a name from inspect_table.");
    sheets = [
      {
        ...sheet,
        csv: selectCsvRows(sheet.csv, { source_rows }),
        sourceRows: source_rows,
        explicitHeader: true,
      },
    ];
  }
  return { sheets, json: converted.summary };
}

export async function executeIngest(job: IngestJob): Promise<IngestResult> {
  const bytes = await readFile(job.inputPath);
  const { config } = job;
  if (job.format === "xlsx") {
    if (
      bytes.length < 2 ||
      bytes.readUInt16LE(0) !== 0x4b50 ||
      !XLSX_TYPES.includes(job.contentType)
    )
      throw new ToolError(
        "INVALID_FILE",
        "The file is not a supported XLSX workbook.",
      );
    assertZipWithinBounds(bytes, config.max_expanded_bytes);
  } else if (job.format === "json") {
    if (!JSON_TYPES.includes(job.contentType))
      throw new ToolError("INVALID_FILE", "The file is not a supported JSON file.");
    assertUtf8Text(bytes, "JSON");
  } else {
    if (!CSV_TYPES.includes(job.contentType))
      throw new ToolError(
        "INVALID_FILE",
        "The file is not a supported UTF-8 CSV file.",
      );
    assertUtf8Text(bytes, "CSV");
  }
  let sheets: IngestedSheet[];
  let json: JsonSummary | undefined;
  try {
    if (job.format === "xlsx")
      sheets = await convertXlsxToCsvSheets(bytes, job.selection);
    else if (job.format === "json") ({ sheets, json } = await jsonSheets(job));
    else
      sheets = [
        {
          name: "Sheet1",
          csv: job.selection ? selectCsvRows(bytes, job.selection) : bytes,
          ...(job.selection
            ? { sourceRows: job.selection.source_rows, explicitHeader: true }
            : {}),
        },
      ];
  } catch (error) {
    if (error instanceof ToolError) throw error;
    throw new ToolError("INVALID_FILE", "The workbook could not be read.");
  }
  if (
    !sheets.length ||
    sheets.length > config.max_sheets ||
    sheets.reduce((n, s) => n + s.csv.length, 0) > config.max_expanded_bytes
  )
    throw new ToolError(
      "INGEST_LIMIT",
      "Workbook is empty or exceeds sheet/expanded size limits.",
    );
  const metadata: SheetMetadata[] = [];
  for (const [i, sheet] of sheets.entries()) {
    if (!sheet.csv.length && sheet.calculation) {
      metadata.push({
        name: sheet.name,
        csv: "",
        columns: [],
        rowCount: 0,
        rejectedRows: 0,
        sampleRows: [],
        calculation: sheet.calculation,
        queryable: false,
      });
      continue;
    }
    const csv = `${i}.csv`;
    const path = join(job.outputDir, csv);
    await writeFile(path, sheet.csv, { mode: 0o600 });
    let description;
    try {
      description = await describeCsv(path, {
        // Generated sheets (JSON records) always carry their header line.
        explicitHeader: sheet.explicitHeader || sheet.jsonPath !== undefined,
      });
    } catch {
      throw new ToolError(
        "INVALID_FILE",
        `Sheet ${sheet.name} could not be parsed as a table.`,
      );
    }
    if (!description.columns.length)
      throw new ToolError("INVALID_FILE", "Sheet has no parseable columns.");
    if (
      sheet.sourceRows &&
      (description.rowCount !== sheet.sourceRows.length ||
        description.rejectedRows)
    )
      throw new ToolError(
        "INVALID_SELECTION",
        "The selected records could not be represented exactly. No comparison was performed.",
      );
    metadata.push({
      ...description,
      name: sheet.name,
      csv,
      ...(sheet.sourceRows
        ? { sourceRows: sheet.sourceRows, explicitHeader: true }
        : sheet.jsonPath !== undefined
          ? { explicitHeader: true }
          : {}),
      ...(sheet.jsonPath !== undefined ? { jsonPath: sheet.jsonPath } : {}),
      ...(sheet.calculation ? { calculation: sheet.calculation } : {}),
    });
  }
  if (Buffer.byteLength(JSON.stringify(metadata)) > MAX_METADATA_BYTES)
    throw new ToolError(
      "INGEST_LIMIT",
      "The workbook's column profile is too large.",
    );
  return { sheets: metadata, ...(json ? { json } : {}) };
}

/** The value at a JSONPath in a JSON file the parent downloaded and wrote for this job. */
export async function executeJsonExtract(job: JsonExtractJob): Promise<JsonExtractOutcome> {
  const bytes = await readFile(job.inputPath);
  assertUtf8Text(bytes, "JSON");
  return extractJsonPath(job.inputPath, job.path, {
    maxChars: job.maxChars,
    memoryMb: job.config.memory_mb,
  });
}

export async function executeQuery(job: QueryJob): Promise<QueryJobResult> {
  const results: QueryJobResult["results"] = [];
  const limits = queryLimits(job.config);
  const exporting =
    job.export !== undefined && job.statements.length === 1 && !job.explain;
  for (const sql of job.statements) {
    try {
      const outcome = await runQuery({
        csvPath: job.csvPath,
        explicitHeader: job.explicitHeader,
        skipRows: job.skipRows,
        sql,
        tables: job.tables,
        explainOnly: job.explain,
        ...limits,
        ...(exporting ? { rowLimit: job.export!.rowLimit } : {}),
      });
      if (exporting) {
        await writeFile(
          job.export!.outputPath,
          toCsv(outcome.columns, outcome.rows),
          {
            mode: 0o600,
          },
        );
        // The caller still gets a bounded preview; the file carries every row.
        const preview = outcome.rows.slice(0, limits.rowLimit);
        results.push({
          ok: true,
          outcome: {
            ...outcome,
            rows: preview,
            returnedRows: preview.length,
            truncated:
              outcome.truncated || outcome.rows.length > preview.length,
            exportedRows: outcome.rows.length,
            exportTruncated: outcome.truncated,
          },
        });
        continue;
      }
      results.push({ ok: true, outcome });
    } catch (error) {
      results.push({
        ok: false,
        code: "QUERY_REJECTED",
        message: modelFacingDiagnostic(error),
      });
    }
  }
  return { results };
}

/**
 * DuckDB error classes that describe the model's own SQL: what it misspelled, which
 * column or function exists instead ("Candidate bindings", "Did you mean"), where the
 * syntax broke, which cast failed. The model fixes its query from these far more often
 * than from a bare rejection.
 */
const SQL_DIAGNOSTIC =
  /^(Failed to extract statements: )?(Parser|Binder|Catalog|Conversion|Invalid Input|Out of Range|Not implemented) Error:/;
const GENERIC_REJECTION =
  "SQL was rejected or failed. Use a single SELECT over t (and any aliases) with column names from inspect_table.";

/**
 * The message the model gets for a failed statement. QueryRejectedError text is ours and
 * tells the model what to change. DuckDB's own diagnostics pass through when they are
 * about the SQL (see `SQL_DIAGNOSTIC`); the rest (I/O, memory, permission, internal) may
 * describe the runtime rather than the query and stay behind one generic text.
 */
export function modelFacingDiagnostic(error: unknown): string {
  if (error instanceof QueryRejectedError) return error.message;
  const message = error instanceof Error ? error.message : "";
  if (!SQL_DIAGNOSTIC.test(message)) return GENERIC_REJECTION;
  // Defensive: no DuckDB SQL diagnostic should name a file, but a path never helps the model.
  const text = message
    .replace(/^Failed to extract statements: /, "")
    .replace(/(?:\/[\w.-]+){2,}/g, "<path>")
    .trim();
  return `${text}\nFix the SQL and call again, using column names from inspect_table.`;
}

export { toCsv };
