// Runs inside sandbox children only: parses untrusted workbooks and executes model-written SQL.
// The parent never imports this file, so neither ExcelJS nor native DuckDB loads in it.
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { ToolError } from "../../errors";
import { describeCsv, QueryRejectedError, runQuery } from "./engine/duckdb";
import { convertXlsxToCsvSheets } from "./engine/xlsx-to-csv";
import { queryLimits } from "./config";
import type { IngestJob, QueryJob, QueryJobResult, SheetMetadata } from "./ports";
import { assertZipWithinBounds } from "./zip-guard";

const XLSX_TYPES = [
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/octet-stream",
];
const CSV_TYPES = ["text/csv", "application/csv", "text/plain", "application/octet-stream"];
const MAX_METADATA_BYTES = 256 * 1024;

export async function executeIngest(job: IngestJob): Promise<{ sheets: SheetMetadata[] }> {
  const bytes = await readFile(job.inputPath);
  const { config } = job;
  if (job.isXlsx) {
    if (
      bytes.length < 2 ||
      bytes.readUInt16LE(0) !== 0x4b50 ||
      !XLSX_TYPES.includes(job.contentType)
    )
      throw new ToolError("INVALID_FILE", "The file is not a supported XLSX workbook.");
    assertZipWithinBounds(bytes, config.max_expanded_bytes);
  } else {
    if (!CSV_TYPES.includes(job.contentType) || bytes.includes(0))
      throw new ToolError("INVALID_FILE", "The file is not a supported UTF-8 CSV file.");
    try {
      new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      throw new ToolError("INVALID_FILE", "CSV files must use UTF-8 encoding.");
    }
  }
  let sheets;
  try {
    sheets = job.isXlsx ? await convertXlsxToCsvSheets(bytes) : [{ name: "Sheet1", csv: bytes }];
  } catch (error) {
    if (error instanceof ToolError) throw error;
    throw new ToolError("INVALID_FILE", "The workbook could not be read.");
  }
  if (
    !sheets.length ||
    sheets.length > config.max_sheets ||
    sheets.reduce((n, s) => n + s.csv.length, 0) > config.max_expanded_bytes
  )
    throw new ToolError("INGEST_LIMIT", "Workbook is empty or exceeds sheet/expanded size limits.");
  const metadata: SheetMetadata[] = [];
  for (const [i, sheet] of sheets.entries()) {
    const csv = `${i}.csv`;
    const path = join(job.outputDir, csv);
    await writeFile(path, sheet.csv, { mode: 0o600 });
    let description;
    try {
      description = await describeCsv(path);
    } catch {
      throw new ToolError("INVALID_FILE", `Sheet ${sheet.name} could not be parsed as a table.`);
    }
    if (!description.columns.length)
      throw new ToolError("INVALID_FILE", "Sheet has no parseable columns.");
    metadata.push({ ...description, name: sheet.name, csv });
  }
  if (Buffer.byteLength(JSON.stringify(metadata)) > MAX_METADATA_BYTES)
    throw new ToolError("INGEST_LIMIT", "The workbook's column profile is too large.");
  return { sheets: metadata };
}

export async function executeQuery(job: QueryJob): Promise<QueryJobResult> {
  const results: QueryJobResult["results"] = [];
  for (const sql of job.statements) {
    try {
      const outcome = await runQuery({
        csvPath: job.csvPath,
        sql,
        tables: job.tables,
        explainOnly: job.explain,
        ...queryLimits(job.config),
      });
      results.push({ ok: true, outcome });
    } catch (error) {
      // QueryRejectedError text is ours and tells the model what to change. Other DuckDB
      // diagnostics may quote file paths and data literals, so they stay out of responses.
      results.push(
        error instanceof QueryRejectedError
          ? { ok: false, code: "QUERY_REJECTED", message: error.message }
          : {
              ok: false,
              code: "QUERY_REJECTED",
              message:
                "SQL was rejected or failed. Use a single SELECT over t (and any aliases) with column names from inspect_table.",
            },
      );
    }
  }
  return { results };
}
