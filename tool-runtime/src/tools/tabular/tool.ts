import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import { RichResult, type CallContext, type ToolDefinition, type ToolView } from "../types";
import { SheetCache } from "./cache";
import { fetchReference, fileReference, type FileReference } from "../files/reference";
import type { TabularConfig } from "./config";
import type { downloadFile } from "./download";
import type { IngestJob, QueryJob, QueryJobResult, QueryOutcome, SheetMetadata } from "./ports";
import { sourceRows } from "./selection";
import { showsTable } from "./view/paging";

/** Runs one job in a sandbox child (see sandbox.ts); injected so tests can run in-process. */
export type TabularExecutor = {
  ingest(job: IngestJob): Promise<{ sheets: SheetMetadata[] }>;
  query(job: QueryJob): Promise<QueryJobResult>;
};

export type TabularDeps = {
  config: TabularConfig;
  /**
   * Optional operator limit (TOOL_RUNTIME_FILE_ORIGINS). Each call's origin comes from Eneo
   * (X-Eneo-File-Origin); when this list is non-empty that origin must also be on it.
   */
  allowedFileOrigins: string[];
  cache: SheetCache;
  executor: TabularExecutor;
  /** Replaceable in tests; production downloads through the pinned, bounded client. */
  download?: typeof downloadFile;
  /** The table view shown with a query's result, in hosts that show tool views. */
  resultView?: ToolView;
};

const ROWS_SHOWN =
  "The user sees these rows as a table directly under your answer, which they can sort, filter, copy, expand and page through. Do not write the rows out again or list the columns. For a browsing request, briefly introduce the table; no extra analysis or export is needed. For an analytical question, explain the relevant findings. If truncated, these rows are only the first page: never infer full-dataset totals or rankings from it; run an aggregate or ordered query when needed.";

// An exported result travels as a file; Eneo admits generated files up to 20 MiB by default.
const MAX_EXPORT_BYTES = 20 * 1024 * 1024;

/** A download name for an exported result; never a path, always .csv. */
export function exportFilename(input: string | undefined): string {
  const base = (input ?? "")
    .normalize("NFC")
    .replace(/\.csv$/i, "")
    .replace(/[\u0000-\u001f\u007f-\u009f"\\/:;*?<>|]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+/, "")
    .slice(0, 100)
    .trim();
  return `${base || "resultat"}.csv`;
}

const fileRef = fileReference;
const sheetName = z
  .string()
  .max(200)
  .optional()
  .describe("Exact sheet name from inspect_table. Required when the workbook has several sheets.");
const extraFiles = z
  .array(
    fileRef
      .extend({
        sheet: sheetName,
        source_rows: sourceRows,
        alias: z
          .string()
          .regex(/^[a-z][a-z0-9_]{0,30}$/)
          .refine((a) => a !== "t", "t is the main table")
          .describe("SQL table name for this file, for example budget or last_year."),
      })
      .strict(),
  )
  .max(4)
  .optional()
  .describe(
    "Further attachments exposed as extra tables for joins: SELECT … FROM t JOIN budget USING (id).",
  );
const selectSql = z
  .string()
  .min(1)
  .max(10_000)
  .describe(
    "One read-only DuckDB SELECT over table t (and any aliases), using column names from inspect_table. Example: SELECT region, SUM(amount) AS total FROM t GROUP BY region. For browsing, select the requested rows without adding LIMIT: the host pages the result. Use LIMIT only for an explicitly requested sample or top-N result, with ORDER BY for rankings. No file paths, URLs, extensions or multiple statements.",
  );

export function tabularTools(deps: TabularDeps): ToolDefinition[] {
  /**
   * Downloads one attachment through its signed URL (Eneo checks access on every call), then
   * returns its parsed sheets from the caller's cache or parses it in a sandbox child.
   */
  async function load(
    ref: FileReference & { sheet?: string; source_rows?: number[] },
    ctx: CallContext,
  ) {
    const { bytes, contentType, isXlsx } = await fetchReference(ref, ctx, {
      allowedFileOrigins: deps.allowedFileOrigins,
      maxBytes: deps.config.max_upload_bytes,
      timeoutMs: deps.config.download_timeout_ms,
      download: deps.download,
    });
    const file = { bytes, contentType };
    const selection = ref.source_rows
      ? {
          sheet: ref.sheet || undefined,
          source_rows: [...new Set(ref.source_rows)].sort((a, b) => a - b),
        }
      : undefined;
    const key = SheetCache.key({
      tenantId: ctx.tenantId,
      userId: ctx.userId,
      kind:
        (isXlsx ? "xlsx-calculation-v1" : "csv") +
        (selection ? ":selection-v1:" + JSON.stringify(selection) : ""),
      sha256: createHash("sha256").update(file.bytes).digest("hex"),
    });
    return deps.cache.getOrBuild(key, async (directory) => {
      const inputPath = join(directory, "original");
      await writeFile(inputPath, file.bytes, { mode: 0o600 });
      const { sheets } = await deps.executor.ingest({
        kind: "tabular_ingest",
        inputPath,
        isXlsx,
        selection,
        contentType: file.contentType,
        outputDir: directory,
        config: deps.config,
      });
      await rm(inputPath, { force: true });
      return sheets;
    });
  }

  function pickSheet(sheets: SheetMetadata[], requested: string | undefined, label: string) {
    if (!requested && sheets.length > 1)
      throw new ToolError(
        "SHEET_REQUIRED",
        `${label} has several sheets. Pass sheet with a name from inspect_table.`,
      );
    const sheet = requested ? sheets.find((s) => s.name === requested) : sheets[0];
    if (!sheet)
      throw new ToolError(
        "UNKNOWN_SHEET",
        `Unknown sheet for ${label}. Use a name from inspect_table.`,
      );
    if (sheet.queryable === false)
      throw new ToolError(
        "NO_SAVED_VALUES",
        "This sheet contains formulas without saved results and no queryable values. Recalculate and save it in Excel, or analyse another sheet. No formulas were recalculated here.",
      );
    return sheet;
  }

  async function tables(
    main: z.infer<typeof fileRef> & { sheet?: string; source_rows?: number[] },
    extras: z.infer<typeof extraFiles>,
    ctx: CallContext,
  ) {
    const aliases = new Set<string>();
    for (const extra of extras ?? []) {
      if (aliases.has(extra.alias))
        throw new ToolError("INVALID_ALIAS", `Duplicate table alias: ${extra.alias}`);
      aliases.add(extra.alias);
    }
    const loaded = await load(main, ctx);
    const sheet = pickSheet(loaded.sheets, main.sheet, main.filename);
    const joined = [];
    const calculationWarnings = sheet.calculation
      ? [{ filename: main.filename, sheet: sheet.name, ...sheet.calculation }]
      : [];
    for (const extra of extras ?? []) {
      const other = await load(extra, ctx);
      const otherSheet = pickSheet(other.sheets, extra.sheet, extra.filename);
      if (otherSheet.calculation)
        calculationWarnings.push({
          filename: extra.filename,
          sheet: otherSheet.name,
          ...otherSheet.calculation,
        });
      joined.push({
        alias: extra.alias,
        csvPath: join(other.directory, otherSheet.csv),
        explicitHeader: otherSheet.explicitHeader,
      });
    }
    return {
      csvPath: join(loaded.directory, sheet.csv),
      sheet,
      explicitHeader: sheet.explicitHeader,
      tables: joined,
      calculation: calculationWarnings.length
        ? {
            calculation_warnings: calculationWarnings,
            calculation_notice:
              "Formula values are saved Excel results, not recalculated here; freshness is unknown. Disclose missing saved results, which are empty values, and qualify conclusions based on them. Recalculate and save the workbook in Excel to obtain those results.",
          }
        : {},
    };
  }

  const inspectInput = z
    .object({
      files: z
        .array(fileRef.extend({ sheet: sheetName, source_rows: sourceRows }).strict())
        .min(1)
        .max(5),
    })
    .strict();
  const queryInput = z
    .object({
      file: fileRef.extend({ sheet: sheetName, source_rows: sourceRows }).strict(),
      files: extraFiles,
      sql: selectSql,
      title: z
        .string()
        .max(120)
        .optional()
        .describe(
          "Short caption saying what the result shows, in the user's language, such as 'Deviation by account group'. Give one whenever display=table: the host lists the conversation's tables and charts by it.",
        ),
      display: z
        .enum(["table", "none"])
        .default("table")
        .describe(
          "Use table when the query result is part of the answer the user should browse. Use none for intermediate calculations, checks, or data prepared for a chart or another tool, unless the user also asked for that table. Both modes return the same data to you; none hides only the interactive table.",
        ),
      explain: z
        .boolean()
        .default(false)
        .describe(
          "Return the query plan instead of results. Leave false when the user needs data.",
        ),
      export: z
        .boolean()
        .default(false)
        .describe(
          `Leave false for showing, browsing, filtering or sorting rows in the conversation, even for large results. Set true when the user asks for a downloadable file or when the result must become a source file for create_spreadsheet or create_chart. Attaches the complete result (up to ${deps.config.export_row_limit} rows) as CSV; pass its reference url to the next tool instead of copying rows.`,
        ),
      export_filename: z
        .string()
        .max(100)
        .optional()
        .describe("File name for the exported CSV, without extension."),
    })
    .strict();
  const assertInput = z
    .object({
      file: fileRef.extend({ sheet: sheetName, source_rows: sourceRows }).strict(),
      files: extraFiles,
      checks: z
        .array(
          z
            .object({
              name: z.string().min(1).max(200).describe("Readable name for the data-quality rule."),
              sql: selectSql.describe(
                "One SELECT whose first cell is boolean true when the rule passes. Example: SELECT COUNT(*) = 0 FROM t WHERE id IS NULL.",
              ),
            })
            .strict(),
        )
        .min(1)
        .max(20),
    })
    .strict();

  const coverage = (outcome: QueryOutcome) => ({
    parsed_rows: outcome.parsedRows,
    rejected_rows: outcome.rejectedRows,
  });

  return [
    {
      name: "inspect_table",
      title: "Inspect table",
      description:
        "Start here when the user wants to view, browse, filter, sort or analyse an attached CSV, TSV or Excel (.xlsx) file. For a native row selection, pass source_rows and sheet unchanged to inspect_table and query_table; the source is filtered before SQL. Pass each file's signed url and filename from the attachment reference, unchanged. Returns sheet names, column names and types, column value profiles, parsed and rejected row counts and up to five sample rows per sheet. These samples describe the file, not the requested result: follow with query_table to show the requested rows or calculate an answer over the full dataset. Do not ask the user to name tools or choose an interactive display. Report rejected rows and missing saved formula results as coverage limitations. Formulas are not recalculated; saved results may be outdated.",
      inputSchema: inspectInput.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const args = inspectInput.parse(raw);
        const files = [];
        for (const ref of args.files) {
          const loaded = await load(ref, ctx);
          files.push({
            filename: ref.filename,
            sheets: loaded.sheets.map((s) => ({
              name: s.name,
              columns: s.columns,
              parsed_rows: s.rowCount,
              ...(s.sourceRows ? { source_rows: s.sourceRows } : {}),
              rejected_rows: s.rejectedRows,
              sample_rows: s.sampleRows,
              ...(s.calculation ? { calculation: s.calculation } : {}),
              ...(s.queryable === false ? { queryable: false } : {}),
            })),
          });
        }
        return {
          files,
          ...(files.some((file) => file.sheets.some((sheet) => sheet.calculation))
            ? {
                calculation_notice:
                  "Formulas were not recalculated. Values are saved Excel results and freshness is unknown. Disclose missing saved results and qualify conclusions; recalculate and save in Excel to obtain missing results.",
              }
            : {}),
        };
      },
    },
    {
      name: "query_table",
      title: "Query table",
      ...(deps.resultView ? { view: deps.resultView } : {}),
      description:
        'Use for ordinary requests such as "show me this file", "show the rows for this region", "sort by amount" or "summarise sales by region", as well as totals, counts, averages, rankings and comparisons over the full CSV/Excel dataset. Call inspect_table first for the actual sheet and column names. Choose display=none for intermediate queries used to calculate an answer or prepare a chart or another tool; do not show a table merely because you queried data. Choose display=table when the table itself is part of the requested answer, and give it a title that tells it apart from the other tables in the conversation. For viewing or browsing, leave export=false: hosts supporting tool views show multi-row results as an interactive table when display=table. The user does not need to ask for a table, name a tool or choose a display mode. Do not add LIMIT merely to keep the answer short; the host pages the result. Export only for a requested downloadable file or a source file needed by create_spreadsheet or create_chart. For a native row selection, pass its source_rows filter unchanged in file; t contains only those source records before your SQL runs. Runs one read-only DuckDB SELECT over table t; pass sheet for multi-sheet workbooks. To combine attachments, list them under files with an alias and JOIN them. Pass signed urls and filenames unchanged. Results report truncation, parsed/rejected coverage and formula limitations for all source files. Disclose missing saved formula results and qualify conclusions based on them; formulas are not recalculated. When the result includes shown, follow that presentation guidance and do not repeat the rows in your answer. Otherwise answer from the returned data, acknowledge truncation and do not claim an interactive table is visible.',
      inputSchema: queryInput.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const args = queryInput.parse(raw);
        const input = await tables(args.file, args.files, ctx);
        const exporting = args.export && !args.explain;
        // The child writes the export into a directory this process owns.
        const directory = exporting
          ? await mkdtemp(join(tmpdir(), "eneo-tool-runtime-export-"))
          : undefined;
        try {
          const outputPath = directory ? join(directory, "result.csv") : undefined;
          const { results } = await deps.executor.query({
            kind: "tabular_query",
            csvPath: input.csvPath,
            explicitHeader: input.explicitHeader,
            tables: input.tables,
            statements: [args.sql],
            explain: args.explain,
            config: deps.config,
            ...(outputPath
              ? {
                  export: {
                    outputPath,
                    rowLimit: deps.config.export_row_limit,
                  },
                }
              : {}),
          });
          const result = results[0]!;
          if (!result.ok) throw new ToolError(result.code, result.message);
          const outcome = result.outcome;
          // Where Eneo shows the rows as a table, the model is told, so they are not
          // written out a second time in the answer.
          const shown =
            deps.resultView !== undefined &&
            ctx.showsViews === true &&
            showsTable({
              rows: outcome.rows,
              plan: args.explain,
              exported: exporting,
              display: args.display,
            });
          const structured = {
            display: args.display,
            sheet: input.sheet.name,
            ...(input.sheet.sourceRows ? { source_rows: input.sheet.sourceRows } : {}),
            columns: outcome.columns,
            rows: outcome.rows,
            returned_rows: outcome.returnedRows,
            truncated: outcome.truncated,
            ...coverage(outcome),
            ...input.calculation,
            ...(shown ? { shown: ROWS_SHOWN } : {}),
          };
          if (!outputPath) return structured;
          const csv = await readFile(outputPath);
          if (csv.length > MAX_EXPORT_BYTES)
            throw new ToolError(
              "EXPORT_TOO_LARGE",
              "The exported result exceeds the file size limit. Select fewer columns or filter the rows.",
            );
          const filename = exportFilename(args.export_filename);
          return new RichResult(
            {
              ...structured,
              export: {
                filename,
                rows: outcome.exportedRows ?? 0,
                truncated: outcome.exportTruncated ?? false,
                delivered:
                  "The full result is attached as a CSV file for the user. Use its reference url for further tools; the rows above are only a preview.",
              },
            },
            [
              {
                uri: `eneo-tool-runtime://tabular/${crypto.randomUUID()}/${encodeURIComponent(filename)}`,
                mimeType: "text/csv",
                blob: csv.toString("base64"),
              },
            ],
          );
        } finally {
          if (directory) await rm(directory, { recursive: true, force: true });
        }
      },
    },
    {
      name: "assert_table",
      title: "Check table",
      description:
        "Validate data-quality rules over a CSV/TSV/Excel table (or the exact source_rows selection supplied in file), such as required values, unique IDs or allowed ranges. Call inspect_table first. Supply up to 20 named SELECT checks over table t; the first cell must be boolean true to pass. Example: SELECT COUNT(*) = COUNT(DISTINCT id) FROM t. False, null and SQL errors are reported per check. Disclose any missing saved formula results even when the checks pass; formulas are not recalculated.",
      inputSchema: assertInput.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const args = assertInput.parse(raw);
        const input = await tables(args.file, args.files, ctx);
        const { results } = await deps.executor.query({
          kind: "tabular_query",
          csvPath: input.csvPath,
          explicitHeader: input.explicitHeader,
          tables: input.tables,
          statements: args.checks.map((c) => c.sql),
          explain: false,
          config: deps.config,
        });
        const checks = args.checks.map((check, i) => {
          const result = results[i];
          if (!result || !result.ok)
            return { name: check.name, passed: false, error: result?.message };
          const value = result.outcome.rows[0]?.[0] ?? null;
          return {
            name: check.name,
            passed: value === true,
            ...(value === true ? {} : { value }),
          };
        });
        return {
          sheet: input.sheet.name,
          checks,
          ...input.calculation,
          passed: checks.every((c) => c.passed),
          parsed_rows: input.sheet.rowCount,
          rejected_rows: input.sheet.rejectedRows,
        };
      },
    },
  ];
}
