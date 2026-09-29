import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import { RichResult, type CallContext, type ToolDefinition } from "../types";
import { SheetCache } from "./cache";
import type { DownloadPolicy, TabularConfig } from "./config";
import { downloadFile } from "./download";
import type { IngestJob, QueryJob, QueryJobResult, QueryOutcome, SheetMetadata } from "./ports";

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
};

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

// Eneo's signed original-download link: /api/v1/files/{id}/original/download/?token=…
const FILE_PATH = /^\/api\/v1\/files\/([0-9a-f-]{36})\/original\/download\/?$/;

const fileRef = z
  .object({
    url: z
      .string()
      .min(1)
      .max(8192)
      .describe("The file's signed Eneo URL, exactly as given in the attachment reference."),
    filename: z
      .string()
      .max(200)
      .regex(/^[^\x00-\x1f/\\]+\.(csv|xlsx)$/i, "Only .csv and .xlsx files are supported")
      .describe("The attachment's filename, ending in .csv or .xlsx."),
  })
  .strict();
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
    "One read-only DuckDB SELECT over table t (and any aliases), using column names from inspect_table. Example: SELECT region, SUM(amount) AS total FROM t GROUP BY region. No file paths, URLs, extensions or multiple statements.",
  );

export function tabularTools(deps: TabularDeps): ToolDefinition[] {
  const download = deps.download ?? downloadFile;

  /**
   * Downloads one attachment through its signed URL (Eneo checks access on every call), then
   * returns its parsed sheets from the caller's cache or parses it in a sandbox child.
   */
  async function load(ref: z.infer<typeof fileRef>, ctx: CallContext) {
    let url: URL;
    try {
      url = new URL(ref.url);
    } catch {
      throw new ToolError("INVALID_URL", "Pass the attachment's signed URL unchanged.");
    }
    const origin = ctx.fileOrigin;
    if (!origin)
      throw new ToolError(
        "FILE_ORIGIN_UNKNOWN",
        "Eneo did not say where its file links point. Set FILE_REFERENCE_BASE_URL (or PUBLIC_ORIGIN) on the Eneo backend.",
      );
    if (deps.allowedFileOrigins.length && !deps.allowedFileOrigins.includes(origin))
      throw new ToolError(
        "FILE_ORIGIN_NOT_ALLOWED",
        "Eneo's file origin is not in this runtime's TOOL_RUNTIME_FILE_ORIGINS. Align the two settings.",
      );
    if (url.searchParams.get("token") === "REDACTED")
      throw new ToolError(
        "STALE_REFERENCE",
        "This link was copied from conversation history, where its token is removed. Use the url from the file's attachment reference in the current request, exactly as given. Do not ask the user to upload the file again.",
      );
    if (url.origin !== origin || !FILE_PATH.test(url.pathname) || !url.searchParams.get("token"))
      throw new ToolError(
        "INVALID_URL",
        "Only signed Eneo attachment URLs are accepted. Pass the url from the attachment reference unchanged.",
      );
    const policy: DownloadPolicy = {
      max_upload_bytes: deps.config.max_upload_bytes,
      download_timeout_ms: deps.config.download_timeout_ms,
      allowed_origins: [{ origin, allow_private: true }],
    };
    const file = await download(ref.url, policy);
    const isXlsx = ref.filename.toLowerCase().endsWith(".xlsx");
    const key = SheetCache.key({
      tenantId: ctx.tenantId,
      userId: ctx.userId,
      kind: isXlsx ? "xlsx" : "csv",
      sha256: createHash("sha256").update(file.bytes).digest("hex"),
    });
    return deps.cache.getOrBuild(key, async (directory) => {
      const inputPath = join(directory, "original");
      await writeFile(inputPath, file.bytes, { mode: 0o600 });
      const { sheets } = await deps.executor.ingest({
        kind: "tabular_ingest",
        inputPath,
        isXlsx,
        contentType: file.contentType,
        outputDir: directory,
        config: deps.config,
      });
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
    return sheet;
  }

  async function tables(
    main: z.infer<typeof fileRef> & { sheet?: string },
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
    for (const extra of extras ?? []) {
      const other = await load(extra, ctx);
      const otherSheet = pickSheet(other.sheets, extra.sheet, extra.filename);
      joined.push({ alias: extra.alias, csvPath: join(other.directory, otherSheet.csv) });
    }
    return { csvPath: join(loaded.directory, sheet.csv), sheet, tables: joined };
  }

  const inspectInput = z.object({ files: z.array(fileRef).min(1).max(5) }).strict();
  const queryInput = z
    .object({
      file: fileRef.extend({ sheet: sheetName }).strict(),
      files: extraFiles,
      sql: selectSql,
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
          `Also deliver the complete result (up to ${deps.config.export_row_limit} rows) as a CSV file attached for the user. Its reference url comes back with the result: pass it to create_spreadsheet or create_chart instead of copying rows.`,
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
      file: fileRef.extend({ sheet: sheetName }).strict(),
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
        "Start here for attached CSV or Excel (.xlsx) files. Pass each file's signed url and filename from the attachment reference, unchanged. Returns sheet names, column names and types, column value profiles, parsed and rejected row counts and up to five sample rows per sheet. Sample rows are not the dataset: never compute totals or conclusions from them; use query_table. Report rejected rows as a coverage limitation.",
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
              rejected_rows: s.rejectedRows,
              sample_rows: s.sampleRows,
            })),
          });
        }
        return { files };
      },
    },
    {
      name: "query_table",
      title: "Query table",
      description:
        "Calculate totals, counts, averages, rankings, grouped summaries, comparisons or filtered rows over the full parsed CSV/Excel table, instead of doing arithmetic over sample rows or a text preview. Call inspect_table first for the actual sheet and column names. Runs one read-only DuckDB SELECT over table t; pass sheet for multi-sheet workbooks. To combine attachments, list them under files with an alias and JOIN them. Pass the signed url and filename unchanged on every call. Results report truncation (a row-limited result is not the whole table) and parsed/rejected coverage. When the user needs the rows themselves (a filtered list, a table for Excel or a chart), set export=true: the complete result becomes a CSV file and its reference url comes back for the next tool.",
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
            tables: input.tables,
            statements: [args.sql],
            explain: args.explain,
            config: deps.config,
            ...(outputPath
              ? { export: { outputPath, rowLimit: deps.config.export_row_limit } }
              : {}),
          });
          const result = results[0]!;
          if (!result.ok) throw new ToolError(result.code, result.message);
          const outcome = result.outcome;
          const structured = {
            sheet: input.sheet.name,
            columns: outcome.columns,
            rows: outcome.rows,
            returned_rows: outcome.returnedRows,
            truncated: outcome.truncated,
            ...coverage(outcome),
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
        "Validate data-quality rules over a full CSV/Excel table, such as required values, unique IDs or allowed ranges. Call inspect_table first. Supply up to 20 named SELECT checks over table t; the first cell must be boolean true to pass. Example: SELECT COUNT(*) = COUNT(DISTINCT id) FROM t. False, null and SQL errors are reported per check.",
      inputSchema: assertInput.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const args = assertInput.parse(raw);
        const input = await tables(args.file, args.files, ctx);
        const { results } = await deps.executor.query({
          kind: "tabular_query",
          csvPath: input.csvPath,
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
          return { name: check.name, passed: value === true, ...(value === true ? {} : { value }) };
        });
        return {
          sheet: input.sheet.name,
          checks,
          passed: checks.every((c) => c.passed),
          parsed_rows: input.sheet.rowCount,
          rejected_rows: input.sheet.rejectedRows,
        };
      },
    },
  ];
}
